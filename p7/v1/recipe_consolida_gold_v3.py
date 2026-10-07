# Dataiku Python recipe: consolida_gold_v3 (mundo cerrado)
# Inputs (Flow): dataset_validated_prepared_labeled_v2 (gold, entity MANUAL),
#                pool_labeling_round_1_labeled (pool auditado, entity regex null),
#                gold_match90_import (match>=90, entidad propagada, w=1.0),
#                gold_sintetico (lexico v1, w=0.3)
# Output (Flow): dataset gold_v3 (name, entity, label_source, w)
# Pesos: gold_validado 1.0 / match_validado 1.0 / manual_pool 0.5 / sintetico 0.3.
# Autoridad: gold > match90 > pool > sintetico. Dedup por name (gold manda).
# 50-90 y <50 NO entran (mundo cerrado). Congelar snapshot antes del reentren.
import dataiku
import pandas as pd

try:
    gold = dataiku.Dataset("dataset_validated_prepared_labeled_v2").get_dataframe()
except Exception:
    gold = dataiku.Dataset("dataset_validated_prepared").get_dataframe()


def _norm_frame(df, col_entity="entity", source="", w=1.0):
    d = df[df[col_entity].notna()].copy()
    d[col_entity] = d[col_entity].astype(str).str.strip().str.lower()
    d = d[d[col_entity] != ""].copy()
    d = d[["name", col_entity]].rename(columns={col_entity: "entity"}).copy()
    d["name"] = d["name"].astype(str).str.strip()
    d = d[d["name"] != ""].copy()
    d["label_source"] = source
    d["w"] = float(w)
    return d[["name", "entity", "label_source", "w"]]


parts = [_norm_frame(gold, "entity", "gold_validado", 1.0)]
for ds, src, w in [("gold_match90_import", "match_validado", 1.0),
                   ("pool_labeling_round_1_labeled", "manual_pool", 0.5),
                   ("gold_sintetico", "sintetico", 0.3)]:
    try:
        d = dataiku.Dataset(ds).get_dataframe()
        e_col = "entity" if "entity" in d.columns else None
        if e_col is None:
            print(f"{ds}: sin columna entity, omitido")
            continue
        if "label_source" in d.columns and "w" in d.columns:
            d = d[d["entity"].notna()].copy()
            d["entity"] = d["entity"].astype(str).str.strip().str.lower()
            d = d[d["entity"] != ""].copy()
            parts.append(d[["name", "entity", "label_source", "w"]].copy())
        else:
            parts.append(_norm_frame(d, e_col, src, w))
        print(f"{ds}: {len(parts[-1])} filas aportadas")
    except Exception as e:
        print(f"{ds}: omitido ({e})")

prior = {"gold_validado": 0, "match_validado": 1,
         "manual_pool": 2, "sintetico": 3}
all_rows = pd.concat(parts, ignore_index=True)
all_rows["_p"] = all_rows["label_source"].map(prior).fillna(9)
all_rows = all_rows.sort_values("_p").drop_duplicates("name", keep="first") \
    .drop(columns="_p").reset_index(drop=True)

dataiku.Dataset("gold_v3").write_with_schema(all_rows)
rep = all_rows.groupby(["label_source", "entity"]).size().reset_index(name="n") \
    .sort_values(["label_source", "n"], ascending=[True, False])
print(f"gold_v3={len(all_rows)}")
print(rep.to_string(index=False))
