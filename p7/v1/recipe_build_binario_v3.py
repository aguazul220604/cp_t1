# Dataiku Python recipe: build_binario_v3 (dataset binario solo-name, mundo cerrado)
# Inputs (Flow): gold_v3 (name, entity, label_source, w) — PII autorizado
#                dataset_validated_prepared_labeled_v2 (gold 21k: name, pii, entity)
# Outputs (Flow): binario_v3 (full + columna split), binario_train_v3,
#                 binario_holdout_v3 (congelado por group_id, 18% hold-out)
# Positivos: gold_v3 (w por fuente). Negativos: SOLO pii=FALSE del 21k (w=1.0).
# Features name-only: key/light/norm/group_id, longitud, n_tokens, tiene_sufijo.
# Prohibidos: dataset/type/description. Hold-out estratificado por pii, sin
# solape de grupos. Congelar Version/Tag de binario_holdout_v3 antes de entrenar.
import re
import unicodedata

import dataiku
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

TEST_SIZE = 0.18
SEED = 0
GATE_ENTITIES = ["correo", "direccion", "fecha_vencimiento", "apellido"]


def _light(s):
    if pd.isna(s):
        return ""
    s = "".join(c for c in unicodedata.normalize("NFD", str(s).lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def _norm(s):
    return re.sub(r"\s*\d+$", "", _light(s)).strip()


def _gid(s):
    return re.sub(r"[\s\-_]", "", _norm(s))


def _is_pii(v):
    if pd.isna(v):
        return False
    if isinstance(v, bool):
        return v
    return str(v).strip().upper() in ("TRUE", "1", "T", "SI")


gold3 = dataiku.Dataset("gold_v3").get_dataframe()
try:
    g21 = dataiku.Dataset("dataset_validated_prepared_labeled_v2").get_dataframe()
except Exception:
    g21 = dataiku.Dataset("dataset_validated_prepared").get_dataframe()

pcol = "pii" if "pii" in g21.columns else "target"
ecol = "entity" if "entity" in g21.columns else None

pos = gold3[gold3["entity"].notna()].copy()
pos["entity"] = pos["entity"].astype(str).str.strip().str.lower()
pos = pos[pos["entity"] != ""].copy()
pos = pos[["name", "entity"]].copy()
pos["pii"] = 1
wmap = dict(zip(gold3["name"].astype(str).str.strip(),
                pd.to_numeric(gold3.get("w", 1.0), errors="coerce").fillna(1.0)))
lsmap = dict(zip(gold3["name"].astype(str).str.strip(),
                 gold3.get("label_source", "gold_validado").fillna("gold_validado").astype(str)))
pos["w"] = pos["name"].astype(str).str.strip().map(wmap).fillna(1.0)
pos["label_source"] = pos["name"].astype(str).str.strip().map(lsmap).fillna("gold_validado")

neg_src = g21[~g21[pcol].map(_is_pii)].copy()
neg = pd.DataFrame({"name": neg_src["name"].astype(str).str.strip()})
neg["entity"] = "NO_PII"
neg["pii"] = 0
neg["w"] = 1.0
neg["label_source"] = "gold_validado"

full = pd.concat([pos, neg], ignore_index=True)
full = full[full["name"] != ""].copy()
# Autoridad PII: si un name esta en gold_v3 PII y en 21k FALSE, manda PII
full = full.sort_values(["pii", "w"], ascending=[False, False]) \
    .drop_duplicates("name", keep="first").reset_index(drop=True)

full["light"] = full["name"].map(_light)
full["key"] = full["light"]
full["name_norm"] = full["name"].map(_norm)
full["group_id"] = full["name"].map(_gid)
full["longitud"] = full["name"].str.len()
full["n_tokens"] = full["name_norm"].str.split().str.len().fillna(0).astype(int)
full["tiene_sufijo"] = full["light"].str.contains(r"\d+$", regex=True).astype(int)
full = full[full["light"] != ""].reset_index(drop=True)

# Split por grupo, estratificado por pii mayoritario del grupo
gtab = full.groupby("group_id").agg(
    pii_maj=("pii", lambda s: int(s.mean() >= 0.5)),
    n=("pii", "size")).reset_index()
gtr, gva = train_test_split(gtab, test_size=TEST_SIZE, random_state=SEED,
                            stratify=gtab["pii_maj"])
tr_mask = full["group_id"].isin(set(gtr["group_id"])).values
assert not (set(gtr["group_id"]) & set(gva["group_id"])), "solape de grupos"
full["split"] = np.where(tr_mask, "train", "holdout")
train = full[tr_mask].reset_index(drop=True)
hold = full[~tr_mask].reset_index(drop=True)

gate = train[train["entity"].isin(GATE_ENTITIES)]["entity"].value_counts()
print(f"binario_v3={len(full)} (PII={(full['pii'] == 1).sum()} "
      f"{(full['pii'] == 1).mean() * 100:.1f}%) | "
      f"train={len(train)} holdout={len(hold)} | grupos={len(gtab)}")
print("w por fuente:\n" + full.groupby("label_source")["w"].agg(["count", "mean"]).to_string())
print("gate 4 fallos en train:\n" + gate.to_string())
missing = [e for e in GATE_ENTITIES if e not in gate.index]
assert not missing, f"gate entities sin PII en train: {missing}"
print("holdout PII por entidad:\n"
      + hold[hold["pii"] == 1]["entity"].value_counts().head(25).to_string())

cols = ["name", "light", "key", "name_norm", "group_id", "longitud",
        "n_tokens", "tiene_sufijo", "pii", "w", "label_source", "entity", "split"]
dataiku.Dataset("binario_v3").write_with_schema(full[cols])
dataiku.Dataset("binario_train_v3").write_with_schema(train[cols])
dataiku.Dataset("binario_holdout_v3").write_with_schema(hold[cols])
