# Dataiku Python recipe: import_match90_gold_v3
# Inputs (Flow): cat_267k_norm, cat_21k_norm,
#                dataset_validated_prepared_labeled_v2 (gold con entity),
#                managed folder fase2_juez_v3 (opcional: chequeo de acuerdo)
# Outputs (Flow): dataset gold_match90_import (name, entity, label_source, w)
#                 + dataset revision_cola_50_90 (name, vecino_21k, similarity,
#                   entity_vecino, entity_juez, prob_juez, motivo)
#                 + managed folder fase5_html (importe.html)
# Doctrina mundo cerrado: solo similarity>=90 + vecino PII importa (w=1.0)
# con entidad propagada del vecino. Desacuerdo con Juez-v3 o prob<0.5
# va a revision, no entra automatico. 50-90 a revision, <50 excluido.
import json
import os
import pickle

import dataiku
import numpy as np
import pandas as pd
from pii_lib.normalize import decidir_import_gold_v3
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors

cat267 = dataiku.Dataset("cat_267k_norm").get_dataframe()
cat21 = dataiku.Dataset("cat_21k_norm").get_dataframe()
try:
    gold = dataiku.Dataset("dataset_validated_prepared_labeled_v2").get_dataframe()
except Exception:
    gold = dataiku.Dataset("dataset_validated_prepared").get_dataframe()

gold_names = set(gold["name"].dropna().astype(str).str.strip())
ent_por_name = dict(zip(gold["name"].astype(str).str.strip(),
                        gold["entity"].astype(str).str.strip().str.lower()))

# Vecino mas cercano 267k -> 21k (variante light, igual que Fase 0/3)
vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
vec.fit(list(cat21["light"].fillna("")) + list(cat267["light"].fillna("")))
X21 = vec.transform(cat21["light"].fillna("").tolist())
X267 = vec.transform(cat267["light"].fillna("").tolist())
dist, idx = NearestNeighbors(n_neighbors=1, metric="cosine").fit(X21).kneighbors(X267)
cat267 = cat267.reset_index(drop=True)
cat21 = cat21.reset_index(drop=True)

# Chequeo Juez-v3 opcional (si faltan artefactos, se importa sin chequeo)
j_vec, j_clases, j_bst = None, None, None
try:
    fdir = dataiku.Folder("fase2_juez_v3").get_path()
    with open(os.path.join(fdir, "vectorizer.pkl"), "rb") as f:
        j_vec = pickle.load(f)
    with open(os.path.join(fdir, "clases.json"), encoding="utf-8") as f:
        j_clases = json.load(f)
    import lightgbm as lgb
    j_bst = lgb.Booster(model_file=os.path.join(fdir, "modelo.txt"))
    print(f"chequeo juez-v3 activo ({len(j_clases)} clases)")
except Exception as e:
    print(f"sin chequeo juez-v3: {e}")


def juez_predecir(keys):
    import lightgbm as _lgb  # noqa
    Xj = j_vec.transform(keys)
    esp = int(j_bst.num_feature())
    if Xj.shape[1] > esp:
        Xj = Xj[:, :esp]
    sc = np.asarray(j_bst.predict(Xj), dtype=float)
    if sc.ndim == 1:
        sc = np.vstack([1 - sc, sc]).T
    if not np.allclose(sc.sum(axis=1), 1.0, atol=1e-3):
        e = np.exp(sc - sc.max(axis=1, keepdims=True))
        sc = e / e.sum(axis=1, keepdims=True)
    return [j_clases[i] for i in sc.argmax(axis=1)], sc.max(axis=1).round(4).tolist()


imp_rows, rev_rows = [], []
cand_keys, cand_meta = [], []
for i, row in cat267.iterrows():
    sim = float((1.0 - dist[i, 0]) * 100.0)
    vecino = cat21.iloc[idx[i, 0]]
    acc, _, _, _ = decidir_import_gold_v3(sim, bool(vecino["pii_majority"]))
    if acc == "importar":
        if row["name"] in gold_names:
            continue
        ent_vec = str(ent_por_name.get(vecino["name"], "") or "").strip().lower()
        if not ent_vec:
            rev_rows.append({"name": row["name"], "vecino_21k": vecino["name"],
                             "similarity": round(sim, 2), "entity_vecino": "",
                             "entity_juez": "", "prob_juez": "",
                             "motivo": "vecino sin entity en gold"})
            continue
        cand_keys.append(row["light"] or "")
        cand_meta.append((row["name"], int(row.get("n_rows", 1)), vecino["name"],
                          round(sim, 2), ent_vec))
    elif acc == "revision":
        rev_rows.append({"name": row["name"], "vecino_21k": vecino["name"],
                         "similarity": round(sim, 2),
                         "entity_vecino": str(ent_por_name.get(vecino["name"], "")),
                         "entity_juez": "", "prob_juez": "",
                         "motivo": "similarity 50-90: revision manual"})

if cand_keys and j_vec is not None:
    je, jp = juez_predecir(cand_keys)
else:
    je, jp = [""] * len(cand_keys), [""] * len(cand_keys)

n_acuerdo = 0
for (nm, nfil, vnm, sim, ent_vec), e_j, p_j in zip(cand_meta, je, jp):
    if j_vec is None or e_j == ent_vec or (isinstance(p_j, str)):
        imp_rows.append({"name": nm, "entity": ent_vec,
                         "label_source": "match_validado", "w": 1.0,
                         "vecino_21k": vnm, "similarity": sim, "n_filas": nfil})
        n_acuerdo += 1
    elif float(p_j) < 0.5 or e_j != ent_vec:
        rev_rows.append({"name": nm, "vecino_21k": vnm, "similarity": sim,
                         "entity_vecino": ent_vec, "entity_juez": e_j,
                         "prob_juez": p_j, "motivo": "desacuerdo juez/vecino"})
    else:
        imp_rows.append({"name": nm, "entity": ent_vec,
                         "label_source": "match_validado", "w": 1.0,
                         "vecino_21k": vnm, "similarity": sim, "n_filas": nfil})
        n_acuerdo += 1

imp = pd.DataFrame(imp_rows, columns=["name", "entity", "label_source", "w",
                                      "vecino_21k", "similarity", "n_filas"])
rev = pd.DataFrame(rev_rows)
dataiku.Dataset("gold_match90_import").write_with_schema(imp)
dataiku.Dataset("revision_cola_50_90").write_with_schema(rev)

rep = imp.groupby("entity").agg(n_nombres=("name", "nunique"),
                                n_filas=("n_filas", "sum")).reset_index() \
    .sort_values("n_nombres", ascending=False) if len(imp) else pd.DataFrame()
html = ("<html><head><meta charset='utf-8'><title>Importe match90</title></head>"
        "<body style='font-family:sans-serif;max-width:1100px;margin:auto'>"
        f"<h1>Importe match90 (mundo cerrado, umbral 90)</h1>"
        f"<p>Importados: {len(imp)} nombres (acuerdo juez/vecino: {n_acuerdo}). "
        f"Revision: {len(rev)} (50-90 + desacuerdos). &lt;50 excluido del train.</p>"
        f"{rep.to_html(index=False) if len(rep) else '<p>Sin importados.</p>'}"
        f"{rev.head(100).to_html(index=False) if len(rev) else ''}</body></html>")
with dataiku.Folder("fase5_html").get_writer("importe.html") as w:
    w.write(html)
print(f"importados={len(imp)} revision={len(rev)}")
if len(rep):
    print(rep.to_string(index=False))
