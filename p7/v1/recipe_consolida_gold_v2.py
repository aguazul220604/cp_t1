# Dataiku Python recipe: consolida_gold_v2
# Inputs (Flow): dataset_validated_prepared_labeled_v2 (gold, entity MANUAL)
#                pool_labeling_round_1_labeled (ronda 1, entity regex auditada)
# Output (Flow): dataset gold_v2 (name, entity, label_source, w)
# Reglas: gold peso 1.0 / pool peso 0.5. Solo entran filas pool con entity != "".
# Deduplica por name: si un name ya esta en gold, manda gold (autoridad validada).
# No toca hold-out (se define despues en el Juez por group_id).
import dataiku
import pandas as pd

PESO_GOLD = 1.0
PESO_POOL = 0.5

try:
    gold = dataiku.Dataset("dataset_validated_prepared_labeled_v2").get_dataframe()
except Exception:
    gold = dataiku.Dataset("dataset_validated_prepared").get_dataframe()
pool = dataiku.Dataset("pool_labeling_round_1_labeled").get_dataframe()

g = gold[gold["entity"].notna()].copy()
g["entity"] = g["entity"].astype(str).str.strip().str.lower()
g = g[g["entity"] != ""].copy()
g = g[["name", "entity"]].copy()
g["label_source"] = "gold_validado"
g["w"] = PESO_GOLD

p = pool[pool["entity"].notna()].copy()
p["entity"] = p["entity"].astype(str).str.strip().str.lower()
p = p[p["entity"] != ""].copy()  # fallback null: vacias se descartan
p = p[["name", "entity"]].copy()
p["label_source"] = "manual_pool"
p["w"] = PESO_POOL

gold_names = set(g["name"].astype(str).str.strip())
p = p[~p["name"].astype(str).str.strip().isin(gold_names)].copy()

gold_v2 = pd.concat([g, p], ignore_index=True).drop_duplicates("name")
# Conflictos residuales mismo name distinta entity (no deberia haber por filtro)
dup = gold_v2[gold_v2.duplicated("name", keep=False)].sort_values("name")
if len(dup):
    print(f"ATENCION: {len(dup)} duplicados name (se conserva gold):\n"
          + dup.head(20).to_string(index=False))
    gold_v2 = gold_v2.sort_values("label_source").drop_duplicates("name", keep="first")

dataiku.Dataset("gold_v2").write_with_schema(gold_v2)

rep = gold_v2.groupby(["label_source", "entity"]).size().reset_index(name="n")
print(f"gold_v2={len(gold_v2)} (gold={len(g)} pool={len(p)})")
print(rep.sort_values(["label_source", "n"], ascending=[True, False]).to_string(index=False))
print("Soporte pool aportado:\n"
      + p["entity"].value_counts().to_string())
