# Dataiku Python recipe: fase1_consolida (Fase 1b — mapping auto-propuesto)
# Inputs (Flow):  catalogo_entidades, dataset_validated_entity
# Outputs (Flow): dataset dataset_validated_entity_v2 (Entity orig + entity_canon)
#                 + dataset catalogo_entidades_v2 (canon, n_clusters, n_names)
#                 + managed folder fase1_html (mapping.html para revision manual)
# Requiere pii_lib/normalize.py con canonical_entity (fusion TELEFONO incluida).
import dataiku
import pandas as pd
from pii_lib.normalize import canonical_entity

catalog = dataiku.Dataset("catalogo_entidades").get_dataframe()
val = dataiku.Dataset("dataset_validated_entity").get_dataframe()

rows = []
for _, r in catalog.iterrows():
    canon, method = canonical_entity(r.get("entity"), r.get("exemplar"))
    rows.append({"entity": r.get("entity"), "cluster": r.get("cluster"),
                 "n": r.get("n"), "exemplar": r.get("exemplar"),
                 "entity_canon": canon, "metodo": method})
mapping = pd.DataFrame(rows)
dataiku.Dataset("catalogo_entidades_v2").write_with_schema(
    mapping.groupby("entity_canon", as_index=False).agg(
        n_clusters=("cluster", "nunique"), n_names=("n", "sum"),
        ejemplos=("exemplar", lambda s: " | ".join(s.head(5)))))

by_cluster = dict(zip(zip(mapping["entity"], mapping["cluster"]),
                      mapping["entity_canon"]))
val["entity_canon"] = [by_cluster.get((e, c))
                       for e, c in zip(val.get("Entity"), val.get("cluster"))]

dataiku.Dataset("dataset_validated_entity_v2").write_with_schema(val)

html = ("<html><head><meta charset='utf-8'><title>Fase 1b — Mapping</title></head>"
        "<body style='font-family:sans-serif;max-width:1100px;margin:auto'>"
        "<h1>Fase 1b — Mapping 188 clusters a canonicas (auto-propuesto)</h1>"
        f"{mapping.sort_values(['entity_canon', 'n'], ascending=[True, False]).to_html(index=False)}"
        "<p>Columna <b>metodo</b>: exact = diccionario, exemplar = keywords del exemplar, "
        "fallback = numero/otros. Ajusta el diccionario en la libreria si algun "
        "mapeo no te convence y re-corre.</p></body></html>")
with dataiku.Folder("fase1_html").get_writer("mapping.html") as w:
    w.write(html)
