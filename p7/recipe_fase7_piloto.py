# Dataiku Python recipe: fase7_piloto (scoring + comparativa vs modelo previo)
# Inputs (Flow):  dataset piloto_columnas + managed folder piloto_tablas
#                 (contiene analisis_pii*.csv del modelo anterior) +
#                 folders fase5_modelo y fase2_juez (artefactos)
# Output (Flow):  dataset piloto_predicciones
# Join con previas por (tabla, key): Archivo sin extension == tabla,
# prob previa 0-100 -> 0-1, "NO PII" -> False.
import glob
import os

import dataiku
import pandas as pd
from pii_lib.normalize import cargar_artefactos, join_key, predecir

cols = dataiku.Dataset("piloto_columnas").get_dataframe()
f5 = dataiku.Folder("fase5_modelo").get_path()
f2 = dataiku.Folder("fase2_juez").get_path()
arts = cargar_artefactos(f5, f2)

base = cols.rename(columns={"tabla": "dataset"})[["dataset", "name"]].copy()
pred = predecir(base, arts)

# ---- previas del modelo anterior ----
prev_files = sorted(glob.glob(os.path.join(
    dataiku.Folder("piloto_tablas").get_path(), "analisis_pii*.csv")))
prev_all = []
for pf in prev_files:
    try:
        pv = pd.read_csv(pf, encoding="utf-8-sig")
    except Exception:
        pv = pd.read_csv(pf, encoding="latin-1")
    pv.columns = [c.strip() for c in pv.columns]
    pv["tabla"] = pv["Archivo"].astype(str).str.replace(
        r"\.xlsx?$", "", regex=True).str.strip()
    pv["key"] = pv["Nombre de Columna"].astype(str).str.strip().map(join_key)
    pv["pii_previo"] = ~pv["Prediccion"].astype(str).str.upper().str.contains("NO")
    pv["prob_previo"] = pd.to_numeric(
        pv["Probabilidad PII (%)"], errors="coerce") / 100.0
    prev_all.append(pv[["tabla", "key", "pii_previo", "prob_previo"]])
prev = pd.concat(prev_all, ignore_index=True) if prev_all else pd.DataFrame(
    columns=["tabla", "key", "pii_previo", "prob_previo"])

pred["tabla"] = pred["dataset"]
pred["key"] = pred["name"].map(join_key)
out = pred.merge(prev, on=["tabla", "key"], how="left")
out["acuerdo"] = (out["pii"] == out["pii_previo"]).where(
    out["pii_previo"].notna(), None)

print("por tabla (n, tasa PII nueva):")
print(out.groupby("tabla").agg(n=("name", "size"),
      tasa_pii=("pii", "mean")).round(3).to_string())
if out["pii_previo"].notna().any():
    print("acuerdo con modelo previo:",
          round(float(out.loc[out["pii_previo"].notna(), "acuerdo"].mean()), 3))
    des = out[out["acuerdo"] == False][  # noqa: E712
        ["tabla", "name", "pii", "prob_pii", "entity",
         "pii_previo", "prob_previo"]].head(30)
    print("top desacuerdos:\n" + des.to_string(index=False))

dataiku.Dataset("piloto_predicciones").write_with_schema(out)
