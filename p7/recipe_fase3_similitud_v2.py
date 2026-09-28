# Dataiku Python recipe: fase3_similitud_v2 (fix 3a — join robusto)
# Inputs (Flow):  cat_267k_norm, cat_21k_norm, dataset_no_validated_prepared
# Output (Flow):  dataset dataset_267k_pii_final (reescribe, mismas columnas + key)
# Cambios vs v1: join por key normalizada (no por name crudo); nombres
# vacios -> nombre_vacio explicito; asercion cero-nulos en pii_final/sample_weight.
# Requiere pii_lib/normalize.py actualizado (join_key).
import dataiku
import pandas as pd
from pii_lib.normalize import assign_pii_final, join_key
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors

cat267 = dataiku.Dataset("cat_267k_norm").get_dataframe()
cat21 = dataiku.Dataset("cat_21k_norm").get_dataframe()
base = dataiku.Dataset("dataset_no_validated_prepared").get_dataframe()

if "key" not in cat267.columns:
    cat267["key"] = cat267["name"].map(join_key)
if "key" not in cat21.columns:
    cat21["key"] = cat21["name"].map(join_key)

# Agrega por key: si varios name crudos colapsan a una key, suma filas
# y decide pii por mayoria; conserva un name representativo.
cat21k = cat21.groupby("key", as_index=False).agg(
    n_rows=("n_rows", "sum"), n_true=("n_true", "sum"),
    light=("light", "first"), name=("name", "first"))
cat21k["pii_majority"] = cat21k["n_true"] * 2 >= cat21k["n_rows"]
cat267k = cat267.groupby("key", as_index=False).agg(
    n_rows=("n_rows", "sum"), n_true=("n_true", "sum"),
    light=("light", "first"), name=("name", "first"))
cat267k["pii_majority"] = cat267k["n_true"] * 2 >= cat267k["n_rows"]

vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
vec.fit(list(cat21k["light"].fillna("")) + list(cat267k["light"].fillna("")))
X21 = vec.transform(cat21k["light"].fillna("").tolist())
X267 = vec.transform(cat267k["light"].fillna("").tolist())
dist, idx = NearestNeighbors(n_neighbors=1, metric="cosine").fit(X21).kneighbors(X267)

meta = {}
for i, row in cat267k.reset_index(drop=True).iterrows():
    sim = float((1.0 - dist[i, 0]) * 100.0)
    vecino = cat21k.iloc[idx[i, 0]]
    pii_final, src, w = assign_pii_final(
        sim, bool(vecino["pii_majority"]), bool(row["pii_majority"]))
    meta[row["key"]] = (vecino["name"], bool(vecino["pii_majority"]), sim,
                        pii_final, src, w)

out = base.copy()
out["key"] = out["name"].map(join_key)
out["vecino_21k"] = out["key"].map(lambda k: meta.get(k, (None,) * 6)[0] if k else None)
out["vecino_pii"] = out["key"].map(lambda k: meta.get(k, (None,) * 6)[1] if k else None)
out["similarity"] = out["key"].map(lambda k: meta.get(k, (None,) * 6)[2] if k else 0.0)
out["pii_final"] = out["key"].map(lambda k: meta.get(k, (None,) * 6)[3] if k else False)
out["label_source"] = out["key"].map(lambda k: meta.get(k, (None,) * 6)[4] if k else None)
out["sample_weight"] = out["key"].map(lambda k: meta.get(k, (None,) * 6)[5] if k else None)

# Nombres vacios: explicitos, nunca nulos.
empty = out["key"] == ""
out.loc[empty, ["vecino_21k", "vecino_pii"]] = [None, False]
out.loc[empty, ["similarity", "pii_final", "label_source", "sample_weight"]] = [
    0.0, False, "nombre_vacio", 0.1]

# Asercion cero-nulos (falla la recipe si reaparece el bug).
assert out["pii_final"].notna().all(), "pii_final con nulos"
assert out["sample_weight"].notna().all(), "sample_weight con nulos"
print(out["label_source"].value_counts().to_string())
print("flips TRUE->FALSE:",
      int(((out["pii"].astype(str).str.upper() == "TRUE") & (~out["pii_final"].astype(bool))).sum()),
      "| FALSE->TRUE:",
      int(((out["pii"].astype(str).str.upper() != "TRUE") & (out["pii_final"].astype(bool))).sum()))

dataiku.Dataset("dataset_267k_pii_final").write_with_schema(out)
