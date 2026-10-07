# Dataiku Python recipe: fase5_binario_v3 (binario PII solo-name, mundo cerrado)
# Inputs (Flow): binario_train_v3, binario_holdout_v3 (congelado por group_id)
# Output (Flow): managed folder fase5_modelo_v3 (modelo.txt|modelo.pkl,
#                vec_name.pkl, encoders.json, metricas.html)
# Features cerradas solo-name: TF-IDF char (2-4) sobre key + longitud,
# n_tokens, tiene_sufijo. Target = pii, sample_weight = w.
# Candidatos: LogReg, SVM lineal calibrado, LightGBM. Threshold FIJO 0.75
# (decision). Se reporta curva F2 de referencia por si 0.75 falla el gate.
# Gates: 23-TEST (las 4: correo/direccion/fecha_vencimiento/apellido en train),
# Recall holdout a 0.75. Carpeta nueva: fase5_modelo actual intacto.
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
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (brier_score_loss, f1_score, precision_recall_curve,
                             precision_score, recall_score)
from sklearn.svm import LinearSVC

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

THR = 0.75
SEED = 0
NUM_COLS = ["longitud", "n_tokens", "tiene_sufijo"]
GATE = ["correo", "direccion", "fecha_vencimiento", "apellido"]

tr = dataiku.Dataset("binario_train_v3").get_dataframe().reset_index(drop=True)
va = dataiku.Dataset("binario_holdout_v3").get_dataframe().reset_index(drop=True)
ytr = tr["pii"].astype(int).values
yva = va["pii"].astype(int).values
wtr = tr["w"].astype(float).values

vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
Xtr_t = vec.fit_transform(tr["key"].fillna("").tolist())
Xva_t = vec.transform(va["key"].fillna("").tolist())
Xtr = hstack([Xtr_t, csr_matrix(tr[NUM_COLS].values)]).tocsr()
Xva = hstack([Xva_t, csr_matrix(va[NUM_COLS].values)]).tocsr()

pos = (ytr * wtr).sum()
neg = ((1 - ytr) * wtr).sum()
spw = float(neg / max(pos, 1))
print(f"train={len(tr)} holdout={len(va)} PII_train={(ytr == 1).sum()} "
      f"spw={spw:.2f}")

cands = {}
cands["logreg"] = CalibratedClassifierCV(
    LogisticRegression(class_weight="balanced", max_iter=2000), cv=3)
cands["svm_lineal"] = CalibratedClassifierCV(LinearSVC(class_weight="balanced",
                                                       random_state=SEED), cv=3)
try:
    from lightgbm import LGBMClassifier
    cands["lgbm"] = LGBMClassifier(objective="binary", num_leaves=63,
                                   n_estimators=500, learning_rate=0.05,
                                   min_child_samples=20, scale_pos_weight=spw,
                                   verbose=-1, random_state=SEED)
except ImportError:
    print("lightgbm no disponible: solo lineales")


def f2max(p, t):
    prec, rec, th = precision_recall_curve(t, p)
    f2 = np.where(prec + rec > 0, 5 * prec * rec / (4 * prec + rec), 0.0)
    j = int(np.argmax(f2))
    return prec, rec, float(f2[j]), float(th[max(j - 1, 0)]) if len(th) else 0.5


rows, fitted, curves = [], {}, {}
for tag, clf in cands.items():
    if tag == "lgbm":
        clf.fit(Xtr, ytr, sample_weight=wtr)
        p = clf.predict_proba(Xva)[:, 1]
    else:
        clf.fit(Xtr, ytr, sample_weight=wtr)
        p = clf.predict_proba(Xva)[:, 1]
    pred = (p >= THR).astype(int)
    prec, rec, f2m, thr_f2 = f2max(p, yva)
    curves[tag] = (prec, rec)
    sl = {}
    for e in GATE:
        m = (va["entity"] == e).values
        sl[e] = round(float(recall_score(yva[m], pred[m], zero_division=0))
                      if m.sum() else float("nan"), 3)
    rows.append({"modelo": tag, "recall@0.75": round(float(recall_score(yva, pred)), 3),
                 "prec@0.75": round(float(precision_score(yva, pred, zero_division=0)), 3),
                 "f1@0.75": round(float(f1_score(yva, pred)), 3),
                 "brier": round(float(brier_score_loss(yva, p)), 4),
                 "f2max_ref": round(f2m, 3), "thr_f2_ref": round(thr_f2, 3),
                 **{f"rec_{e}": v for e, v in sl.items()}})
    fitted[tag] = clf
    fn = va[(pred == 0) & (yva == 1)][["name", "entity"]].copy()
    fn["prob"] = p[(pred == 0) & (yva == 1)]
    print(f"[{tag}] FN={len(fn)}:\n"
          + (fn.sort_values("prob", ascending=False).head(15).to_string(index=False)
             if len(fn) else "(sin FN)"))

comp = pd.DataFrame(rows).sort_values(["recall@0.75", "f1@0.75"], ascending=False)
W = comp.iloc[0]["modelo"]
print(comp.to_string(index=False))
print(f"GANADOR={W} (threshold fijo {THR})")

# Refit ganador sobre train (holdout intacto) y artefactos a carpeta nueva
final = fitted[W]
folder = dataiku.Folder("fase5_modelo_v3")
fdir = folder.get_path()
with open(os.path.join(fdir, "vec_name.pkl"), "wb") as f:
    pickle.dump(vec, f)
is_lgbm = type(final).__name__ == "LGBMClassifier"
if is_lgbm:
    final.booster_.save_model(os.path.join(fdir, "modelo.txt"))
    model_type = "lgbm_booster"
else:
    with open(os.path.join(fdir, "modelo.pkl"), "wb") as f:
        pickle.dump(final, f)
    model_type = "sklearn_calibrated"
with open(os.path.join(fdir, "encoders.json"), "w", encoding="utf-8") as f:
    json.dump({"model_type": model_type, "winner": W, "threshold": THR,
               "features": ["tfidf_char_key_2_4"] + NUM_COLS,
               "target": "pii", "mundo": "cerrado_solo_name",
               "te_map": {}, "te_global": 0.0, "top_types": [],
               "num_cols": NUM_COLS}, f, ensure_ascii=False)

fig, ax = plt.subplots(figsize=(6, 4))
for tag, (prec, rec) in curves.items():
    ax.plot(rec, prec, label=f"{tag} (F2ref={comp.set_index('modelo').loc[tag, 'f2max_ref']})")
ax.axvline(0.88, color="red", linestyle="--", label="gate recall 0.88")
ax.set_xlabel("recall")
ax.set_ylabel("precision")
ax.set_title(f"PR holdout congelado @thr fijo {THR} (estrella = punto F2max ref)")
ax.legend()
buf = io.BytesIO()
fig.tight_layout()
fig.savefig(buf, format="png")
plt.close(fig)
img = base64.b64encode(buf.getvalue()).decode()

gate_ok = all(comp.set_index("modelo").loc[W, f"rec_{e}"] == 1.0 for e in GATE)
html = ("<html><head><meta charset='utf-8'><title>Fase 5 v3 — Binario solo-name</title></head>"
        "<body style='font-family:sans-serif;max-width:1000px;margin:auto'>"
        f"<h1>Binario v3 solo-name — ganador: {W} @thr={THR}</h1>"
        f"{comp.to_html(index=False)}"
        f"<p>Gate 4 fallos (rec a 0.75 por slice): "
        f"{ {e: comp.set_index('modelo').loc[W, f'rec_{e}'] for e in GATE} } "
        f"→ {'PASS' if gate_ok else 'FAIL: revisar FN arriba y criterio/lexico'}.</p>"
        f"<img src='data:image/png;base64,{img}'/>"
        "<p>Hold-out congelado por group_id (nombres no vistos). Features: "
        "TF-IDF char key + longitud/n_tokens/tiene_sufijo. Sin dataset/type/description. "
        "Carpeta nueva fase5_modelo_v3; operativo actual intacto.</p></body></html>")
with open(os.path.join(fdir, "metricas.html"), "w", encoding="utf-8") as f:
    f.write(html)
