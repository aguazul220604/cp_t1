# Dataiku Python recipe: fase7_prepara (headers xlsx -> piloto_columnas)
# Input (Flow):  managed folder piloto_tablas (*.xlsx piloto + analisis_pii*.csv)
# Output (Flow): dataset piloto_columnas (tabla, name)
# Toma la primera fila de cada xlsx como nombres de columna.
# Si el code env no trae openpyxl, convierte los xlsx a CSV y avisa.
import os

import dataiku
import pandas as pd

folder = dataiku.Folder("piloto_tablas")
fdir = folder.get_path()
files = sorted(f for f in folder.list_paths_in_partition()
               if f.lower().endswith((".xlsx", ".xls")))

try:
    import openpyxl  # noqa: F401
except ImportError:
    raise RuntimeError(
        "Falta openpyxl en el code env: instala openpyxl o sube los "
        "headers como CSV (una columna 'name' + columna 'tabla').")

rows = []
for f in files:
    tabla = os.path.splitext(os.path.basename(f))[0]
    cols = pd.read_excel(os.path.join(fdir, f), nrows=0).columns.tolist()
    for c in cols:
        c = str(c).strip()
        if c and c.lower() != "nan":
            rows.append({"tabla": tabla, "name": c})

out = pd.DataFrame(rows, columns=["tabla", "name"])
print(f"tablas={len(files)} columnas={len(out)}")
print(out.groupby("tabla").size().to_string())
dataiku.Dataset("piloto_columnas").write_with_schema(out)
