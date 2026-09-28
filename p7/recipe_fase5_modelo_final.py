# Dataiku Python recipe: fase5_modelo_final (Fase 5 + Fase 6 en una)
# Input (Flow):  dataset_entrenamiento_final (congelar Version/Tag antes)
# Output (Flow): managed folder fase5_modelo (modelo.txt, vec_name.pkl,
#                vec_desc.pkl, encoders.json, metricas.html)
# Target = pii_final + sample_weight. Features SOLO produccion:
# name, description, type, dataset, longitud, has_description.
# Excluidas por fuga: entity/prob_entity, vecino_*/similarity/label_source,
# pii/target originales. Variante A sin descripcion; B con descripcion +
# Feature Dropout 60%. Threshold por max F2-score (Fase 6).
import base64
import io
import json
import os
import pickle

import dataiku
import matplotlib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import (f1_score, precision_recall_curve, recall_score)
from sklearn.model_selection import StratifiedKFold, train_test_split

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

DROPOUT = 0.60
TOP_TYPES = 20
TE_ALPHA = 10.0
SEED = 0

df = dataiku.Dataset("dataset_entrenamiento_final").get_dataframe().reset_index(drop=True)
y = df["pii_final"].astype(bool).astype(int).values
sw = df["sample_weight"].astype(float).values

tr_idx, va_idx = train_test_split(np.arange(len(df)), test_size=0.20,
                                  stratify=y, random_state=SEED)
tr, va = df.iloc[tr_idx].reset_index(drop=True), df.iloc[va_idx].reset_index(drop=True)
ytr, yva = y[tr_idx], y[va_idx]
swtr = sw[tr_idx]

# ---- dataset: target encoding out-of-fold (train) ----
skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
te_oof = np.zeros(len(tr))
glob = float(np.average(ytr, weights=swtr))
for a, b in skf.split(tr, ytr):
    m = tr.iloc[a].groupby("dataset").apply(
        lambda g: (ytr[g.index] * swtr[g.index]).sum() / swtr[g.index].sum())
    n = tr.iloc[a].groupby("dataset").size()
    te_oof[b] = tr.iloc[b]["dataset"].map(
        (m * n + TE_ALPHA * glob) / (n + TE_ALPHA)).fillna(glob).values
full_map = tr.groupby("dataset").apply(
    lambda g: (ytr[g.index] * swtr[g.index]).sum() / swtr[g.index].sum())
full_n = tr.groupby("dataset").size()
te_map = ((full_map * full_n + TE_ALPHA * glob) / (full_n + TE_ALPHA)).to_dict()
te_tr = te_oof
te_va = va["dataset"].map(te_map).fillna(glob).values

# ---- type: one-hot top-20 ----
top_types = tr["type"].fillna("").value_counts().head(TOP_TYPES).index.tolist()

def type_ohe(s):
    s = s.fillna("").where(s.isin(top_types), "OTROS")
    return pd.get_dummies(s, prefix="typ").reindex(
        columns=["typ_" + t for t in top_types] + ["typ_OTROS"], fill_value=0)

type_tr = type_ohe(tr["type"]).values
type_va = type_ohe(va["type"]).values

# ---- texto ----
vec_name = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
Xn_tr = vec_name.fit_transform(tr["key"].fillna("").tolist())
Xn_va = vec_name.transform(va["key"].fillna("").tolist())
vec_desc = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), max_features=20000)
vec_desc.fit(tr["description"].fillna("").tolist())
Xd_tr = vec_desc.transform(tr["description"].fillna("").tolist())
Xd_va = vec_desc.transform(va["description"].fillna("").tolist())

rng = np.random.RandomState(SEED)
drop = rng.rand(len(tr)) < DROPOUT
Xd_tr_d = Xd_tr.copy().tolil()
Xd_tr_d[drop] = 0
Xd_tr_d = Xd_tr_d.tocsr()
Xd_va_0 = csr_matrix(Xd_va.shape)  # val enmascarada (escenario produccion)

num_tr = np.vstack([tr["longitud"].values, tr["has_description"].astype(int).values,
                    te_tr]).T
num_va = np.vstack([va["longitud"].values, va["has_description"].astype(int).values,
                    te_va]).T
num_tr_d = num_tr.copy()
num_tr_d[drop, 1] = 0  # has_description enmascarado en train


A_tr = hstack([Xn_tr, csr_matrix(num_tr), csr_matrix(type_tr)]).tocsr()
A_va = hstack([Xn_va, csr_matrix(num_va), csr_matrix(type_va)]).tocsr()
B_tr = hstack([Xn_tr, Xd_tr_d, csr_matrix(num_tr_d), csr_matrix(type_tr)]).tocsr()
B_va = hstack([Xn_va, Xd_va, csr_matrix(num_va), csr_matrix(type_va)]).tocsr()
B_va0 = hstack([Xn_va, Xd_va_0, csr_matrix(
    np.vstack([va["longitud"].values, np.zeros(len(va)), te_va]).T),
    csr_matrix(type_va)]).tocsr()
A_va0 = hstack([Xn_va, csr_matrix(num_va), csr_matrix(type_va)]).tocsr()  # A no usa desc

pos = (ytr * swtr).sum()
neg = ((1 - ytr) * swtr).sum()
spw = float(neg / max(pos, 1))
results = {}
for tag, Mtr, Mva, Mva0 in [("A", A_tr, A_va, A_va0), ("B", B_tr, B_va, B_va0)]:
    clf = LGBMClassifier(objective="binary", num_leaves=63, n_estimators=500,
                         learning_rate=0.05, min_child_samples=20,
                         scale_pos_weight=spw, verbose=-1, random_state=SEED)
    clf.fit(Mtr, ytr, sample_weight=swtr)
    results[tag] = {"clf": clf,
                    "val": clf.predict_proba(Mva)[:, 1],
                    "val0": clf.predict_proba(Mva0)[:, 1]}


def f2_curve(p, t):
    prec, rec, th = precision_recall_curve(t, p)
    f2 = np.where(prec + rec > 0, 5 * prec * rec / (4 * prec + rec), 0.0)
    j = int(np.argmax(f2))
    thr = float(th[max(j - 1, 0)]) if len(th) else 0.5
    return prec, rec, th, float(f2[j]), thr, float(prec[j]), float(rec[j])


comp = []
curves = {}
for tag in ("A", "B"):
    for suf, key in (("intacta", "val"), ("enmascarada", "val0")):
        p = results[tag][key]
        prec, rec, th, f2, thr, pr, rc = f2_curve(p, yva)
        f1 = float(f1_score(yva, (p >= 0.5).astype(int)))
        comp.append({"variante": tag, "val": suf,
                     "recall@0.5": round(float(recall_score(yva, (p >= 0.5).astype(int))), 3),
                     "f1@0.5": round(f1, 3), "f2max": round(f2, 3),
                     "thr_f2": round(thr, 3),
                     "prec_en_thr": round(pr, 3), "rec_en_thr": round(rc, 3)})
        if suf == "enmascarada":
            curves[tag] = (prec, rec, th)
comp_df = pd.DataFrame(comp)
masked = comp_df[comp_df["val"] == "enmascarada"]
winner = masked.sort_values(["f2max", "f1@0.5"], ascending=False).iloc[0]
W = winner["variante"]

# ---- refit final 100% con variante ganadora ----
Xfull_name = vec_name.transform(df["key"].fillna("").tolist())
Xfull_desc = vec_desc.transform(df["description"].fillna("").tolist())
if W == "B":
    d = rng.rand(len(df)) < DROPOUT
    Xfull_desc = Xfull_desc.copy().tolil()
    Xfull_desc[d] = 0
    Xfull_desc = Xfull_desc.tocsr()
    num_full = np.vstack([df["longitud"].values,
                          (df["has_description"].astype(int).values * (~d)).astype(int),
                          df["dataset"].map(te_map).fillna(glob).values]).T
    Xfull = hstack([Xfull_name, Xfull_desc, csr_matrix(num_full),
                    csr_matrix(type_ohe(df["type"]).values)]).tocsr()
else:
    num_full = np.vstack([df["longitud"].values,
                          df["has_description"].astype(int).values,
                          df["dataset"].map(te_map).fillna(glob).values]).T
    Xfull = hstack([Xfull_name, csr_matrix(num_full),
                    csr_matrix(type_ohe(df["type"]).values)]).tocsr()
final = LGBMClassifier(objective="binary", num_leaves=63, n_estimators=500,
                       learning_rate=0.05, min_child_samples=20,
                       scale_pos_weight=float(((1 - y) * sw).sum() / max((y * sw).sum(), 1)),
                       verbose=-1, random_state=SEED)
final.fit(Xfull, y, sample_weight=sw)

folder = dataiku.Folder("fase5_modelo")
fdir = folder.get_path()
final.booster_.save_model(os.path.join(fdir, "modelo.txt"))
with open(os.path.join(fdir, "vec_name.pkl"), "wb") as f:
    pickle.dump(vec_name, f)
with open(os.path.join(fdir, "vec_desc.pkl"), "wb") as f:
    pickle.dump(vec_desc, f)
with open(os.path.join(fdir, "encoders.json"), "w", encoding="utf-8") as f:
    json.dump({"variante": W, "threshold": float(winner["thr_f2"]),
               "dropout": DROPOUT, "te_map": te_map, "te_global": glob,
               "top_types": top_types, "target": "pii_final"}, f, ensure_ascii=False)

fig, ax = plt.subplots(figsize=(6, 4))
for tag, (prec, rec, _) in curves.items():
    ax.plot(rec, prec, label=f"variante {tag}")
ax.set_xlabel("recall")
ax.set_ylabel("precision")
ax.set_title("Curva PR en validacion enmascarada (escenario produccion)")
ax.legend()
buf = io.BytesIO()
fig.tight_layout()
fig.savefig(buf, format="png")
plt.close(fig)
img = base64.b64encode(buf.getvalue()).decode()

html = ("<html><head><meta charset='utf-8'><title>Fase 5+6 — Modelo final</title></head>"
        "<body style='font-family:sans-serif;max-width:1000px;margin:auto'>"
        f"<h1>Fase 5+6 — ganadora: variante {W} (thr F2={winner['thr_f2']})</h1>"
        f"{comp_df.to_html(index=False)}"
        f"<p>Threshold produccion: <b>{winner['thr_f2']}</b> (F2max={winner['f2max']}, "
        f"precision={winner['prec_en_thr']}, recall={winner['rec_en_thr']} en val enmascarada).</p>"
        f"<img src='data:image/png;base64,{img}'/>"
        "<p>Features: name TF-IDF char + descrip TF-IDF word (solo B) + longitud + "
        "has_description + dataset TE-OOF + type OHE. Excluidas por fuga: "
        "entity/prob_entity, vecino_*/similarity/label_source, pii/target originales.</p>"
        "</body></html>")
with open(os.path.join(fdir, "metricas.html"), "w", encoding="utf-8") as f:
    f.write(html)
print(comp_df.to_string(index=False))
print(f"GANADORA={W} THR={winner['thr_f2']} F2={winner['f2max']}")
