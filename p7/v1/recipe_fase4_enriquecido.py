# Dataiku Python recipe: fase4_enriquecido (dataset final de entrenamiento)
# Input (Flow):  dataset_267k_pii_entity
# Output (Flow): dataset dataset_entrenamiento_final (filtrado has_name=TRUE)
# Agrega has_description + longitud; conserva has_name/key/entity/prob_entity/
# pii_final/label_source/sample_weight. Checks de integridad + log composicion.
# El snapshot/congelado se hace en Dataiku via Version/Tag del dataset o
# duplicando a dataset_entrenamiento_final_FREEZE_YYYYMMDD (manual en el Flow).
import dataiku
import pandas as pd

df = dataiku.Dataset("dataset_267k_pii_entity").get_dataframe()
out = df.copy()

out["has_description"] = out["description"].notna() & (
    out["description"].astype(str).str.strip() != "")
out["longitud"] = out["name"].fillna("").astype(str).str.len()

train = out[out["has_name"].astype(bool)].reset_index(drop=True)

# ---- checks de integridad (filas con nombre) ----
assert train["pii_final"].notna().all(), "pii_final con nulos en train"
assert train["sample_weight"].notna().all(), "sample_weight con nulos en train"
assert train["longitud"].gt(0).all(), "longitud=0 con has_name=TRUE"
assert ((train["sample_weight"] > 0) & (train["sample_weight"] <= 1.0)).all(), \
    "sample_weight fuera de (0,1]"
ent_null_ok = train["entity"].isna() == (~train["pii_final"].astype(bool))
assert ent_null_ok.all(), "entity nula no coincide con pii_final=FALSE"
print(f"train={len(train)} (de {len(out)}), "
      f"pii_final True={int(train['pii_final'].astype(bool).sum())} "
      f"({train['pii_final'].astype(bool).mean()*100:.1f}%)")
print("label_source:\n" + train["label_source"].value_counts().to_string())
print("has_description True: "
      f"{int(train['has_description'].sum())} "
      f"({train['has_description'].mean()*100:.1f}%)")
print("longitud media/mediana: "
      f"{train['longitud'].mean():.1f}/{train['longitud'].median():.1f}")
print("entity top:\n" + train["entity"].value_counts().head(8).to_string())

dataiku.Dataset("dataset_entrenamiento_final").write_with_schema(train)
