# Dataiku Python recipe: fase3b_entity_v2 (Juez-23 + fallback -> entity/prob_entity)
# Inputs (Flow):  dataset_267k_pii_final + managed folder fase2_juez_v2
# Output (Flow):  dataset dataset_267k_pii_entity_v2
# Igual que fase3b_entity pero lee fase2_juez_v2 (23 clases) y aplica
# fallback por reglas si prob_entity < 0.5. Resto NULL donde no es PII.
import json
import os
import pickle
import re
import unicodedata

import dataiku
import lightgbm as lgb
import numpy as np
import pandas as pd

UMBRAL_FALLBACK = 0.50
REGLAS = [
    ("curp", ("curp",)), ("rfc", ("rfc",)),
    ("nss", ("nss", "seguro_social")),
    ("correo", ("correo", "email", "mail")),
    ("sexo", ("sexo", "genero")),
    ("fecha_vencimiento", ("venc", "expira", "expiry", "vigencia")),
    ("fecha_nacimiento", ("nacim", "fnacim", "birth")),
]


def _light(s):
    if pd.isna(s):
        return ""
    s = "".join(c for c in unicodedata.normalize("NFD", str(s).lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


base = dataiku.Dataset("dataset_267k_pii_final").get_dataframe()
fdir = dataiku.Folder("fase2_juez_v2").get_path()

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
    keys = out.loc[mask, "key"].fillna("").map(_light).tolist()
    X = vec.transform(keys)
    scores = np.asarray(bst.predict(X))
    if scores.ndim == 1:
        scores = np.vstack([1 - scores, scores]).T
    if not np.allclose(scores.sum(axis=1), 1.0, atol=1e-3):
        e = np.exp(scores - scores.max(axis=1, keepdims=True))
        scores = e / e.sum(axis=1, keepdims=True)
    idx = scores.argmax(axis=1)
    ents = [clases[i] for i in idx]
    probs = np.round(scores.max(axis=1), 4)
    toc = 0
    for j, (k, e, p) in enumerate(zip(keys, ents, probs)):
        if p < UMBRAL_FALLBACK:
            kk = f" {k} ".replace("_", " ")
            for ent, kws in REGLAS:
                if any(kw in kk for kw in kws) and ent in clases and ent != e:
                    ents[j] = ent
                    toc += 1
                    break
    out.loc[mask, "entity"] = ents
    out.loc[mask, "prob_entity"] = probs
    print(f"fallback corrigio {toc} de {int(mask.sum())}")

print(f"predichas: {int(mask.sum())} | top: "
      f"{out.loc[mask, 'entity'].value_counts().head(10).to_dict()}")
dataiku.Dataset("dataset_267k_pii_entity_v2").write_with_schema(out)
