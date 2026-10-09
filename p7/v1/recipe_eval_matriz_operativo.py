# Dataiku Python recipe: eval_matriz_operativo (SIN reentrenar)
# Inputs (Flow): binario_holdout_v3 (congelado) + managed folder fase5_modelo_operativo
# Output (Flow): managed folder fase5_modelo_operativo_metricas:
#                eval_operativo.html + confusion_matrix.csv + metrics.json
# NO toca modelo.txt / vec_name.pkl / encoders.json. Solo scoring post-hoc.
# Soporta operativo legacy (variante A/B con type OHE + TE + desc) y v3
# (solo-name). Holdout v3 no trae dataset/type/description -> se usan
# defaults de produccion (te_global, OTROS, has_description=0, desc=0),
# igual que hace la webapp en inferencia y que B_va0 en el train.
import base64
import io
import json
import os
import pickle

import dataiku
import matplotlib
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, hstack
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                             precision_score, recall_score)

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

THR_BACKEND = 0.667
THRS_ANEXO = [0.05, 0.08, 0.10, 0.13, 0.15, 0.20, 0.25, 0.30, 0.40,
              0.50, 0.60, 0.667, 0.75, 0.90]
NUM_COLS_V3 = ["longitud", "n_tokens", "tiene_sufijo"]


def f2_from_pr(prec, rec):
    return float(5 * prec * rec / (4 * prec + rec)) if (prec + rec) > 0 else 0.0


# ---- artefactos operativos (solo lectura) ----
f_in = dataiku.Folder("fase5_modelo_operativo").get_path()
with open(os.path.join(f_in, "vec_name.pkl"), "rb") as f:
    vec = pickle.load(f)
with open(os.path.join(f_in, "encoders.json"), encoding="utf-8") as f:
    enc = json.load(f)

THR_OP = float(enc.get("threshold", THR_BACKEND))
THR_PRINCIPAL = THR_OP
print(f"threshold operativo encoders.json={THR_OP} | backend v5.1={THR_BACKEND}")

# Detecta mundo del operativo: legacy A/B (con top_types/TE) vs v3 (solo-name).
variante = enc.get("variante", None)
top_types = list(enc.get("top_types", []))
te_map = dict(enc.get("te_map", {}) or {})
te_global = float(enc.get("te_global", 0.0))
num_cols_enc = list(enc.get("num_cols", []))
is_legacy = bool(variante in ("A", "B") or len(top_types) > 0 or len(te_map) > 0)
print(f"variante={variante} legacy={is_legacy} top_types={len(top_types)} "
      f"num_cols_enc={num_cols_enc}")

vec_desc = None
if is_legacy and variante == "B":
    with open(os.path.join(f_in, "vec_desc.pkl"), "rb") as f:
        vec_desc = pickle.load(f)

if os.path.exists(os.path.join(f_in, "modelo.txt")):
    import lightgbm as lgb
    clf = lgb.Booster(model_file=os.path.join(f_in, "modelo.txt"))
    predict = lambda X: np.asarray(clf.predict(X)).ravel()  # noqa
    esp = int(clf.num_feature())
else:
    with open(os.path.join(f_in, "modelo.pkl"), "rb") as f:
        clf = pickle.load(f)
    predict = lambda X: np.asarray(clf.predict_proba(X))[:, 1]  # noqa
    esp = None
print(f"modelo espera {esp} features")

# ---- holdout congelado ----
va = dataiku.Dataset("binario_holdout_v3").get_dataframe().reset_index(drop=True)
yva = va["pii"].astype(int).values
n = len(va)
keys = va["key"].fillna("").tolist()
Xn = vec.transform(keys)

if is_legacy:
    # Reconstruye features legacy con defaults de produccion.
    if "longitud" in va.columns:
        longitud = va["longitud"].values.astype(float)
    else:
        longitud = va["name"].fillna("").astype(str).str.len().values.astype(float)
    has_desc = np.zeros(n)  # holdout sin description = escenario prod enmascarado
    te = np.full(n, te_global, dtype=float)  # dataset desconocido -> global
    num = np.vstack([longitud, has_desc, te]).T
    n_typ = len(top_types) + 1  # top + OTROS
    typ = np.zeros((n, n_typ), dtype=np.int8)
    typ[:, -1] = 1  # todo a OTROS (holdout v3 no trae type)
    if variante == "B":
        assert vec_desc is not None, "variante B requiere vec_desc.pkl"
        Xd = csr_matrix((n, len(vec_desc.vocabulary_)))
        Xva = hstack([Xn, Xd, csr_matrix(num), csr_matrix(typ)]).tocsr()
    else:
        Xva = hstack([Xn, csr_matrix(num), csr_matrix(typ)]).tocsr()
else:
    NUM_COLS = num_cols_enc if len(num_cols_enc) == 3 else NUM_COLS_V3
    Xva = hstack([Xn, csr_matrix(va[NUM_COLS].values)]).tocsr()

print(f"Xva construido {tuple(Xva.shape)} vs esperado {esp}")
if esp is not None and Xva.shape[1] != esp:
    if Xva.shape[1] > esp:
        Xva = Xva[:, :esp]
        print(f"truncado a {tuple(Xva.shape)}")
    else:
        # Rellena con ceros (no deberia pasar si la rama es correcta).
        from scipy.sparse import csr_matrix as _csr
        pad = _csr((n, esp - Xva.shape[1]))
        Xva = hstack([Xva, pad]).tocsr()
        print(f"rellenado a {tuple(Xva.shape)}")
assert esp is None or Xva.shape[1] == esp, f"ancho final {Xva.shape[1]} vs {esp}"
p = predict(Xva)


def metricas_en_thr(thr):
    pr = (p >= thr).astype(int)
    tn, fp, fn, tp = confusion_matrix(yva, pr, labels=[0, 1]).ravel()
    prec = float(precision_score(yva, pr, zero_division=0))
    rec = float(recall_score(yva, pr))
    return {
        "thr": float(thr),
        "TN": int(tn), "FP": int(fp), "FN": int(fn), "TP": int(tp),
        "n": int(len(yva)),
        "accuracy": round(float(accuracy_score(yva, pr)), 4),
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1": round(float(f1_score(yva, pr)), 4),
        "f2": round(f2_from_pr(prec, rec), 4),
        "especificidad": round(float(tn / max(tn + fp, 1)), 4),
    }


m = metricas_en_thr(THR_PRINCIPAL)
print(f"PRINCIPAL thr={THR_PRINCIPAL}: {m}")
cm = np.array([[m["TN"], m["FP"]], [m["FN"], m["TP"]]])

extra = None
if abs(THR_OP - THR_BACKEND) > 1e-9:
    extra = metricas_en_thr(THR_BACKEND)
    print(f"BACKEND thr={THR_BACKEND}: {extra}")

rows = [metricas_en_thr(t) for t in THRS_ANEXO]
comp = pd.DataFrame(rows)

va_sc = va[["name", "entity"]].copy()
va_sc["prob"] = np.round(p, 4)
va_sc["pred"] = (p >= THR_PRINCIPAL).astype(int)
va_sc["real"] = yva
fn_top = va_sc[(va_sc["pred"] == 0) & (va_sc["real"] == 1)].sort_values(
    "prob", ascending=False).head(15)
fp_top = va_sc[(va_sc["pred"] == 1) & (va_sc["real"] == 0)].sort_values(
    "prob", ascending=False).head(15)

fig, ax = plt.subplots(figsize=(4.5, 4))
ax.imshow(cm, cmap="Blues")
ax.set_xticks([0, 1], ["Pred NO PII", "Pred PII"])
ax.set_yticks([0, 1], ["Real NO PII", "Real PII"])
ax.set_title(f"Matriz confusion operativo @thr={THR_PRINCIPAL}")
for i in range(2):
    for j in range(2):
        ax.text(j, i, int(cm[i, j]), ha="center", va="center",
                fontsize=14, fontweight="bold")
fig.tight_layout()
buf = io.BytesIO()
fig.savefig(buf, format="png")
plt.close(fig)
img = base64.b64encode(buf.getvalue()).decode()

# ---- salidas: SIEMPRE al folder de OUTPUT, nunca al input ----
try:
    f_out = dataiku.Folder("fase5_modelo_operativo_metricas").get_path()
except Exception:
    f_out = f_in  # fallback local / flow antiguo con mismo folder
print(f"escribe en: {f_out}")
pd.DataFrame([[m["TN"], m["FP"]], [m["FN"], m["TP"]]],
             index=["Real NO_PII", "Real PII"],
             columns=["Pred NO_PII", "Pred PII"]).to_csv(
    os.path.join(f_out, "confusion_matrix.csv"), encoding="utf-8")
with open(os.path.join(f_out, "metrics.json"), "w", encoding="utf-8") as f:
    json.dump({"principal": m, "backend_ref": extra,
               "barrido": rows, "threshold_operativo": THR_OP,
               "threshold_backend": THR_BACKEND,
               "variante": variante, "legacy": is_legacy,
               "n_holdout": int(len(yva)),
               "modelo_tocado": False}, f, ensure_ascii=False, indent=2)

extra_html = ""
if extra is not None:
    extra_html = (f"<h2>Referencia backend v5.1 @thr={THR_BACKEND}</h2>"
                  f"{pd.DataFrame([extra]).to_html(index=False)}"
                  "<p>El backend v5.1 usa THRESHOLD=0.667 fijo en codigo; "
                  "si encoders.json difiere, alinear en cutover manual.</p>")
nota = ("<p>Operativo legacy A/B: holdout v3 sin dataset/type/description "
        "se evalua con defaults de produccion "
        "(te_global, type=OTROS, has_description=0, desc=0), "
        "igual que B_va0 en entrenamiento y que la webapp.</p>" if is_legacy
        else "<p>Operativo v3 solo-name: features key + longitud/n_tokens/tiene_sufijo.</p>")
html = ("<html><head><meta charset='utf-8'>"
        "<title>Eval operativo — matriz confusion</title></head>"
        "<body style='font-family:sans-serif;max-width:1100px;margin:auto'>"
        f"<h1>Modelo operativo — matriz @thr={THR_PRINCIPAL} (SIN reentrenar)</h1>"
        f"<p>Holdout congelado: <b>{len(yva)} filas</b> "
        f"(PII={(yva == 1).sum()}, NO_PII={(yva == 0).sum()}). "
        f"Modelo: fase5_modelo_operativo/modelo.txt (variante={variante}). "
        "Este recipe solo hace scoring; no modifica el modelo.</p>"
        f"{nota}"
        f"{pd.DataFrame([m]).to_html(index=False)}"
        f"<img src='data:image/png;base64,{img}'/>"
        f"{extra_html}"
        f"<h2>FN top (falsos negativos @thr={THR_PRINCIPAL})</h2>"
        f"{fn_top.to_html(index=False) if len(fn_top) else '<p>Sin FN.</p>'}"
        f"<h2>FP top (falsos positivos @thr={THR_PRINCIPAL})</h2>"
        f"{fp_top.to_html(index=False) if len(fp_top) else '<p>Sin FP.</p>'}"
        f"<h2>Anexo barrido (contexto, no cambia operativo)</h2>"
        f"{comp.to_html(index=False)}"
        "</body></html>")
with open(os.path.join(f_out, "eval_operativo.html"), "w", encoding="utf-8") as f:
    f.write(html)
print("OK eval operativo -> eval_operativo.html + confusion_matrix.csv + metrics.json")
print(f"Matriz @thr={THR_PRINCIPAL}: TN={m['TN']} FP={m['FP']} FN={m['FN']} TP={m['TP']}")
