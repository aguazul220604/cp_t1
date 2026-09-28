# Dataiku Python recipe: fase3b_entity (Juez -> entity/prob_entity)
# Inputs (Flow):  dataset_267k_pii_final + managed folder fase2_juez
# Output (Flow):  dataset dataset_267k_pii_entity (= pii_final + entity/prob_entity)
# Solo predice donde has_name=TRUE & pii_final=TRUE; resto queda NULL.
# Vectoriza la columna key (es el light ya normalizado).
import json
import os
import pickle

import dataiku
import lightgbm as lgb
import numpy as np
import pandas as pd

base = dataiku.Dataset("dataset_267k_pii_final").get_dataframe()
folder = dataiku.Folder("fase2_juez")
fdir = folder.get_path()

with open(os.path.join(fdir, "vectorizer.pkl"), "rb") as f:
    vec = pickle.load(f)
with open(os.path.join(fdir, "clases.json"), encoding="utf-8") as f:
    clases = json.load(f)
bst = lgb.Booster(model_file=os.path.join(fdir, "modelo.txt"))

out = base.copy()
out["entity"] = None
out["prob_entity"] = np.nan

mask = out["has_name"].astype(bool) & (out["pii_final"].astype(bool))
if mask.sum():
    X = vec.transform(out.loc[mask, "key"].fillna("").tolist())
    scores = np.asarray(bst.predict(X))
    if scores.ndim == 1:  # binario por seguridad
        scores = np.vstack([1 - scores, scores]).T
    if not np.allclose(scores.sum(axis=1), 1.0, atol=1e-3):
        e = np.exp(scores - scores.max(axis=1, keepdims=True))
        scores = e / e.sum(axis=1, keepdims=True)
    idx = scores.argmax(axis=1)
    out.loc[mask, "entity"] = [clases[i] for i in idx]
    out.loc[mask, "prob_entity"] = np.round(scores.max(axis=1), 4)

print(f"predichas: {int(mask.sum())} | entity top: "
      f"{out.loc[mask, 'entity'].value_counts().head(5).to_dict()}")
print(f"prob_entity media: {float(out.loc[mask, 'prob_entity'].mean()):.3f}")

dataiku.Dataset("dataset_267k_pii_entity").write_with_schema(out)
