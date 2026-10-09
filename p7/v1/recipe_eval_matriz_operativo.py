# Dataiku Python recipe: eval_matriz_operativo (SIN reentrenar)
# Inputs (Flow): binario_holdout_v3 (congelado) + managed folder fase5_modelo_operativo
# Outputs (Flow): mismo folder fase5_modelo_operativo (+3 archivos nuevos):
#                 eval_operativo.html + confusion_matrix.csv + metrics.json
# NO toca modelo.txt / vec_name.pkl / encoders.json. Solo scoring post-hoc.
# Principal: threshold operativo (encoders.json, fallback 0.667 = backend v5.1).
# Anexo: barrido [0.05..0.90] con 0.667 marcado, para contexto negocio.
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

THR_BACKEND = 0.667  # backend v5.1 webapp_v1/backend.py THRESHOLD
THRS_ANEXO = [0.05, 0.08, 0.10, 0.13, 0.15, 0.20, 0.25, 0.30, 0.40,
              0.50, 0.60, 0.667, 0.75, 0.90]
NUM_COLS_DEFAULT = ["longitud", "n_tokens", "tiene_sufijo"]


def f2_from_pr(prec, rec):
    return float(5 * prec * rec / (4 * prec + rec)) if (prec + rec) > 0 else 0.0


# ---- artefactos operativos (solo lectura) ----
fdir = dataiku.Folder("fase5_modelo_operativo").get_path()
with open(os.path.join(fdir, "vec_name.pkl"), "rb") as f:
    vec = pickle.load(f)
with open(os.path.join(fdir, "encoders.json"), encoding="utf-8") as f:
    enc = json.load(f)

NUM_COLS = list(enc.get("num_cols", NUM_COLS_DEFAULT))
THR_OP = float(enc.get("threshold", THR_BACKEND))
# Principal = operativo real; si difiere del backend, se reportan ambos.
THR_PRINCIPAL = THR_OP
print(f"threshold operativo encoders.json={THR_OP} | backend v5.1={THR_BACKEND}")

is_lgbm = enc.get("model_type", "") == "lgbm_booster" or os.path.exists(
    os.path.join(fdir, "modelo.txt"))
if os.path.exists(os.path.join(fdir, "modelo.txt")):
    import lightgbm as lgb
    clf = lgb.Booster(model_file=os.path.join(fdir, "modelo.txt"))
    predict = lambda X: np.asarray(clf.predict(X)).ravel()  # noqa
    esp = int(clf.num_feature())
else:
    with open(os.path.join(fdir, "modelo.pkl"), "rb") as f:
        clf = pickle.load(f)
    predict = lambda X: np.asarray(clf.predict_proba(X))[:, 1]  # noqa
    esp = None

# ---- holdout congelado (no reentrenar, no modificar split) ----
va = dataiku.Dataset("binario_holdout_v3").get_dataframe().reset_index(drop=True)
yva = va["pii"].astype(int).values
Xva = hstack([vec.transform(va["key"].fillna("").tolist()),
              csr_matrix(va[NUM_COLS].values)]).tocsr()
if esp is not None:
    if Xva.shape[1] > esp:
        Xva = Xva[:, :esp]
    assert Xva.shape[1] == esp, f"ancho holdout {Xva.shape[1]} vs modelo {esp}"
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


# ---- principal operativo ----
m = metricas_en_thr(THR_PRINCIPAL)
print(f"PRINCIPAL thr={THR_PRINCIPAL}: {m}")
cm = np.array([[m["TN"], m["FP"]], [m["FN"], m["TP"]]])

# Si operativo != backend, reportar backend tambien (sin cambiar nada).
extra = None
if abs(THR_OP - THR_BACKEND) > 1e-9:
    extra = metricas_en_thr(THR_BACKEND)
    print(f"BACKEND thr={THR_BACKEND}: {extra}")

# ---- anexo barrido ----
rows = [metricas_en_thr(t) for t in THRS_ANEXO]
comp = pd.DataFrame(rows)

# ---- FN/FP top para negocio ----
va_sc = va[["name", "entity"]].copy()
va_sc["prob"] = np.round(p, 4)
va_sc["pred"] = (p >= THR_PRINCIPAL).astype(int)
va_sc["real"] = yva
fn_top = va_sc[(va_sc["pred"] == 0) & (va_sc["real"] == 1)].sort_values(
    "prob", ascending=False).head(15)
fp_top = va_sc[(va_sc["pred"] == 1) & (va_sc["real"] == 0)].sort_values(
    "prob", ascending=False).head(15)

# ---- figura matriz ----
fig, ax = plt.subplots(figsize=(4.5, 4))
im = ax.imshow(cm, cmap="Blues")
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

# ---- salidas (solo archivos nuevos, modelo intacto) ----
pd.DataFrame([[m["TN"], m["FP"]], [m["FN"], m["TP"]]],
             index=["Real NO_PII", "Real PII"],
             columns=["Pred NO_PII", "Pred PII"]).to_csv(
    os.path.join(fdir, "confusion_matrix.csv"), encoding="utf-8")
with open(os.path.join(fdir, "metrics.json"), "w", encoding="utf-8") as f:
    json.dump({"principal": m, "backend_ref": extra,
               "barrido": rows, "threshold_operativo": THR_OP,
               "threshold_backend": THR_BACKEND,
               "n_holdout": int(len(yva)),
               "modelo_tocado": False}, f, ensure_ascii=False, indent=2)

extra_html = ""
if extra is not None:
    extra_html = (f"<h2>Referencia backend v5.1 @thr={THR_BACKEND}</h2>"
                  f"{pd.DataFrame([extra]).to_html(index=False)}"
                  "<p>El backend v5.1 usa THRESHOLD=0.667 fijo en codigo; "
                  "si encoders.json difiere, alinear en cutover manual.</p>")
html = ("<html><head><meta charset='utf-8'>"
        "<title>Eval operativo — matriz confusion</title></head>"
        "<body style='font-family:sans-serif;max-width:1100px;margin:auto'>"
        f"<h1>Modelo operativo — matriz @thr={THR_PRINCIPAL} (SIN reentrenar)</h1>"
        f"<p>Holdout congelado: <b>{len(yva)} filas</b> "
        f"(PII={(yva == 1).sum()}, NO_PII={(yva == 0).sum()}). "
        f"Modelo: fase5_modelo_operativo/modelo.txt + vec_name.pkl. "
        "Este recipe solo hace scoring; no modifica el modelo.</p>"
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
with open(os.path.join(fdir, "eval_operativo.html"), "w", encoding="utf-8") as f:
    f.write(html)
print("OK eval operativo -> eval_operativo.html + confusion_matrix.csv + metrics.json")
print(f"Matriz @thr={THR_PRINCIPAL}: TN={m['TN']} FP={m['FP']} FN={m['FN']} TP={m['TP']}")
