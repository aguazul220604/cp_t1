# Dataiku Python recipe: eval_threshold_v3 (barrido post-hoc, SIN reentrenar)
# Inputs (Flow): binario_holdout_v3 (congelado) + managed folder fase5_modelo_v3
#               (+ opcional dataset test_23_columnas con columna name: tus 23 TEST)
# Outputs (Flow): managed folder fase5_modelo_v3 (eval_threshold.html +
#                 threshold_v3.json con recomendado). NO toca el modelo ni el
#                 operativo: el cutover se hace a mano tras revisar el reporte.
# Barrido [0.05..0.9]: recall/prec/F1 global, F2max, slices gate + recall
# por entidad PII, y 23/23 en TEST si existe. Recomendado = max F2 con
# recall>=0.88 y prec>=0.30 si existe; si no, max F2 puro (se reporta el gap).
import json
import os
import pickle

import dataiku
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, hstack
from sklearn.metrics import f1_score, precision_score, recall_score

THRS = [0.05, 0.08, 0.10, 0.13, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.75, 0.90]
NUM_COLS = ["longitud", "n_tokens", "tiene_sufijo"]
GATE = ["correo", "direccion", "fecha_vencimiento", "apellido",
        "credenciales_id", "bienes_patrimonio", "otro_pii"]

fdir = dataiku.Folder("fase5_modelo_v3").get_path()
with open(os.path.join(fdir, "vec_name.pkl"), "rb") as f:
    vec = pickle.load(f)
with open(os.path.join(fdir, "encoders.json"), encoding="utf-8") as f:
    enc = json.load(f)
is_lgbm = enc.get("model_type", "") == "lgbm_booster"
if is_lgbm:
    import lightgbm as lgb
    clf = lgb.Booster(model_file=os.path.join(fdir, "modelo.txt"))
    predict = lambda X: np.asarray(clf.predict(X)).ravel()  # noqa
else:
    with open(os.path.join(fdir, "modelo.pkl"), "rb") as f:
        clf = pickle.load(f)
    predict = lambda X: np.asarray(clf.predict_proba(X))[:, 1]  # noqa

va = dataiku.Dataset("binario_holdout_v3").get_dataframe().reset_index(drop=True)
yva = va["pii"].astype(int).values
Xva = hstack([vec.transform(va["key"].fillna("").tolist()),
              csr_matrix(va[NUM_COLS].values)]).tocsr()
esp = getattr(clf, "num_feature", lambda: Xva.shape[1])()
if Xva.shape[1] > esp:
    Xva = Xva[:, :esp]
assert Xva.shape[1] == esp, f"ancho holdout {Xva.shape[1]} vs modelo {esp}"
p = predict(Xva)


def f2_of(t):
    pr = (p >= t).astype(int)
    prec = precision_score(yva, pr, zero_division=0)
    rec = recall_score(yva, pr)
    f2 = 5 * prec * rec / (4 * prec + rec) if (prec + rec) else 0.0
    return prec, rec, f2


rows = []
for t in THRS:
    pr = (p >= t).astype(int)
    d = {"thr": t, "recall": round(float(recall_score(yva, pr)), 3),
         "prec": round(float(precision_score(yva, pr, zero_division=0)), 3),
         "f1": round(float(f1_score(yva, pr)), 3)}
    prec, rec, f2 = f2_of(t)
    d["f2"] = round(float(f2), 3)
    for e in GATE:
        m = (va["entity"] == e).values & (yva == 1)
        d[f"rec_{e}"] = (round(float(recall_score(yva[m], pr[m], zero_division=0)), 3)
                         if m.sum() else float("nan"))
    rows.append(d)
comp = pd.DataFrame(rows)
ok = comp[(comp["recall"] >= 0.88) & (comp["prec"] >= 0.30)]
reco = (ok.sort_values("f2", ascending=False).iloc[0]["thr"]
        if len(ok) else comp.sort_values("f2", ascending=False).iloc[0]["thr"])
reco = float(reco)
print(comp.to_string(index=False))
print(f"RECOMENDADO={reco} (recall>=0.88 & prec>=0.30: "
      f"{'sí' if len(ok) else 'no: max F2 puro'})")

# Recall por entidad PII en holdout al recomendado (diagnostico, no gate)
pr = (p >= reco).astype(int)
ent_rows = []
for e, grp in va[yva == 1].groupby("entity"):
    m = (va["entity"] == e).values & (yva == 1)
    ent_rows.append({"entity": e, "n_holdout": int(m.sum()),
                     f"rec@{reco}": round(float(recall_score(
                         yva[m], pr[m], zero_division=0)), 3)})
ent_rep = pd.DataFrame(ent_rows).sort_values(f"rec@{reco}")

# TEST-23 opcional (dataset test_23_columnas con columna name)
test_rep, test_n = "", 0
try:
    t23 = dataiku.Dataset("test_23_columnas").get_dataframe()
    names = t23["name"].dropna().astype(str).str.strip().tolist()
    import re as _re
    import unicodedata as _ud

    def _l(s):
        s = "".join(c for c in _ud.normalize("NFD", str(s).lower())
                    if _ud.category(c) != "Mn")
        return _re.sub(r"\s+", " ", s).strip()

    keys = [_l(n) for n in names]
    num_t = np.array([[len(n), len(_l(n).split()),
                       int(bool(_re.search(r"\d+$", k)))]
                      for n, k in zip(names, keys)])
    Xt = hstack([vec.transform(keys), csr_matrix(num_t)]).tocsr()
    if Xt.shape[1] > esp:
        Xt = Xt[:, :esp]
    pt = predict(Xt)
    miss = [(n, round(float(v), 3)) for n, v in zip(names, pt) if v < reco]
    test_n = len(names) - len(miss)
    test_rep = (f"<p>TEST-23 a thr={reco}: <b>{test_n}/{len(names)} PII</b>. "
                f"Faltantes: {miss if miss else 'ninguno'}.</p>")
    print(f"TEST-23: {test_n}/{len(names)} a thr={reco}; faltan={miss}")
except Exception as e:
    test_rep = f"<p>TEST-23 no evaluado (dataset test_23_columnas ausente: {e}).</p>"
    print(f"TEST-23 omitido: {e}")

with open(os.path.join(fdir, "threshold_v3.json"), "w", encoding="utf-8") as f:
    json.dump({"recomendado": reco, "thr_anterior": 0.75,
               "criterio": "max F2 con recall>=0.88 & prec>=0.30"}, f)
html = ("<html><head><meta charset='utf-8'><title>Eval threshold v3</title></head>"
        "<body style='font-family:sans-serif;max-width:1100px;margin:auto'>"
        f"<h1>Threshold operativo v3 — recomendado: {reco} (anterior 0.75)</h1>"
        f"{comp.to_html(index=False)}"
        f"<h2>Recall por entidad a thr={reco}</h2>{ent_rep.to_html(index=False)}"
        f"{test_rep}"
        "<p>Cutover manual: tras validar, copiar este valor a "
        "fase5_modelo_operativo/encoders.json (o promover carpeta) y re-probar webapp.</p>"
        "</body></html>")
with open(os.path.join(fdir, "eval_threshold.html"), "w", encoding="utf-8") as f:
    f.write(html)
