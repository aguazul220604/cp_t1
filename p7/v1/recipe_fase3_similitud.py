# Dataiku Python recipe: fase3_similitud (Fase 3a, sin Juez)
# Inputs (Flow):  cat_267k_norm, cat_21k_norm, dataset_no_validated_prepared
# Outputs (Flow): dataset dataset_267k_pii_final
#   Columnas nuevas a nivel fila: vecino_21k, vecino_pii, similarity, pii_final,
#   label_source, sample_weight.
# Regla congelada Fase 0 (variante light): >=90 validado_21k/1.0;
# 50-90 evidencia_parcial/sim/100; <50 sin_evidencia_mantenido/0.3 (conserva pii original).
import dataiku
import pandas as pd
from pii_lib.normalize import assign_pii_final, parse_pii
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors

cat267 = dataiku.Dataset("cat_267k_norm").get_dataframe()
cat21 = dataiku.Dataset("cat_21k_norm").get_dataframe()
base = dataiku.Dataset("dataset_no_validated_prepared").get_dataframe()

vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
vec.fit(list(cat21["light"].fillna("")) + list(cat267["light"].fillna("")))
X21 = vec.transform(cat21["light"].fillna("").tolist())
X267 = vec.transform(cat267["light"].fillna("").tolist())
dist, idx = NearestNeighbors(n_neighbors=1, metric="cosine").fit(X21).kneighbors(X267)

sim_map, meta = {}, {}
for i, row in cat267.reset_index(drop=True).iterrows():
    sim = float((1.0 - dist[i, 0]) * 100.0)
    vecino = cat21.iloc[idx[i, 0]]
    pii_orig = bool(row["pii_majority"])
    pii_final, src, w = assign_pii_final(sim, bool(vecino["pii_majority"]), pii_orig)
    sim_map[row["name"]] = sim
    meta[row["name"]] = (vecino["name"], bool(vecino["pii_majority"]),
                         pii_final, src, w)

out = base.copy()
out["vecino_21k"] = out["name"].map(lambda n: meta.get(n, (None,) * 5)[0])
out["vecino_pii"] = out["name"].map(lambda n: meta.get(n, (None,) * 5)[1])
out["similarity"] = out["name"].map(sim_map)
out["pii_final"] = out["name"].map(lambda n: meta.get(n, (None,) * 5)[2])
out["label_source"] = out["name"].map(lambda n: meta.get(n, (None,) * 5)[3])
out["sample_weight"] = out["name"].map(lambda n: meta.get(n, (None,) * 5)[4])

dataiku.Dataset("dataset_267k_pii_final").write_with_schema(out)
