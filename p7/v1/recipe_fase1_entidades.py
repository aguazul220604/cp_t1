# Dataiku Python recipe: fase1_entidades
# Input (Flow):  cat_21k_norm
# Outputs (Flow): dataset dataset_validated_entity + dataset catalogo_entidades
#                 + managed folder fase1_html (catalog.html)
# Requiere pii_lib/normalize.py en Library Editor.
import numpy as np

import dataiku
import pandas as pd
from pii_lib.normalize import (build_char_tfidf, cluster_affinity_sweep,
                               cluster_fallback, name_clusters,
                               normalize_light_split)
from sklearn.metrics.pairwise import cosine_similarity

cat21 = dataiku.Dataset("cat_21k_norm").get_dataframe()
pos = cat21[cat21["pii_majority"]].reset_index(drop=True)

_, X = build_char_tfidf(pos["light"].tolist())
S = cosine_similarity(X)

sweep = cluster_affinity_sweep(np.asarray(S))
# Elige barrido con k en [5, 25]; si ninguno, fallback aglomerativo.
chosen, k_chosen = None, None
for pref, lab in sweep.items():
    k = len(set(lab)) - (1 if -1 in list(lab) else 0)
    if 5 <= k <= 25 and (chosen is None or abs(k - 12) < abs(k_chosen - 12)):
        chosen, k_chosen = lab, k
if chosen is None:
    best = max(sweep.values(), key=lambda l: len(set(l)))
    chosen = cluster_fallback(X, labels=best)

entity_by_cluster = name_clusters(
    [normalize_light_split(t) for t in pos["light"].tolist()], chosen)
pos["cluster"] = list(chosen)
pos["Entity"] = pos["cluster"].map(entity_by_cluster)

# Propaga Entity al 21k completo (solo PII=TRUE la tienen; resto nulo).
cat_out = cat21.merge(pos[["name", "Entity", "cluster"]], on="name", how="left")
dataiku.Dataset("dataset_validated_entity").write_with_schema(cat_out)

rows = []
for (ent, cl), grp in pos.groupby(["Entity", "cluster"]):
    rows.append({"entity": ent, "cluster": int(cl), "n": len(grp),
                 "exemplar": grp.sort_values("n_rows", ascending=False)["name"].iloc[0]})
catalog = pd.DataFrame(rows).sort_values("n", ascending=False)
dataiku.Dataset("catalogo_entidades").write_with_schema(catalog)

html = ("<html><head><meta charset='utf-8'><title>Fase 1 — Entidades</title></head>"
        "<body style='font-family:sans-serif;max-width:1000px;margin:auto'>"
        f"<h1>Fase 1 — Entidades (k={len(set(chosen))})</h1>"
        f"{catalog.to_html(index=False)}"
        "<p>Revisa sanity-check: si algun Entity sale fragmentado "
        "(ej. 'ca' en vez de 'tel'), renombralo manualmente antes de Fase 2.</p>"
        "</body></html>")
with dataiku.Folder("fase1_html").get_writer("catalog.html") as w:
    w.write(html)
