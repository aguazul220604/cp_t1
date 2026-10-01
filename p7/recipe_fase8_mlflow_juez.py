import json
import os
import shutil

import dataiku
import mlflow
import pandas as pd
from pii_lib.pyfunc_model import JuezEntityModel

CODE_ENV = "CodeEnv39CleanProjects" 
SAVED_MODEL_NAME = "juez_entity_saved"

# Cargar la lista de clases del modelo Juez
with open(os.path.join(dataiku.Folder("fase2_juez").get_path(),
                       "clases.json"), encoding="utf-8") as f:
    clases = json.load(f)
print(f"clases={len(clases)}: {clases}")

# Filtrar
val = dataiku.Dataset("dataset_validated_entity_v2").get_dataframe()
eva = val[val["entity_canon"].isin(clases)].reset_index(drop=True)
dataiku.Dataset("dataset_eval_juez").write_with_schema(eva)
print(f"eval_juez={len(eva)}")

with open(os.path.join(dataiku.Folder("fase2_juez").get_path(),
                       "juez_clases.json"), encoding="utf-8") as f:
    clases = json.load(f)
print(f"clases={len(clases)}: {clases}")

f2 = dataiku.Folder("fase2_juez").get_path()
model_dir = os.path.join(dataiku.Folder("mlflow_juez_tmp").get_path(), "juez_model")
shutil.rmtree(model_dir, ignore_errors=True)
mlflow.pyfunc.save_model(
    path=model_dir,
    python_model=JuezEntityModel(),
    artifacts={
        "juez_model": os.path.join(f2, "modelo.txt"),
        "juez_vec": os.path.join(f2, "vectorizer.pkl"),
        "juez_clases": os.path.join(f2, "clases.json"),
    },
    pip_requirements=["scikit-learn", "lightgbm", "pandas", "numpy", "scipy"],
)
print("MLflow model guardado en mlflow_juez_tmp/juez_model")

client = dataiku.api_client()
project = client.get_project(dataiku.default_project_key())
sm = None
for item in project.list_saved_models():
    info = item if isinstance(item, dict) else item.get_settings().get_raw()
    if info.get("name") == SAVED_MODEL_NAME:
        sm = project.get_saved_model(info.get("id"))
        break
if sm is None:
    sm = project.create_mlflow_pyfunc_model(SAVED_MODEL_NAME, "MULTICLASS")
    print(f"Saved Model creado: {SAVED_MODEL_NAME}")
else:
    print(f"Saved Model existente: {SAVED_MODEL_NAME}")

try:
    n_ver = len(sm.list_versions())
except Exception:
    n_ver = 0
vid = f"v{n_ver + 1}"
mf_id = {f["name"]: f["id"] for f in project.list_managed_folders()}["mlflow_juez_tmp"]
ver = sm.import_mlflow_version_from_managed_folder(
    vid, mf_id, "juez_model", CODE_ENV)
print(f"version importada: {vid}")

try:
    ver.set_core_metadata("entity_canon", clases, "dataset_eval_juez")
except Exception as e:
    print(f"WARN set_core_metadata: {e}")
try:
    ver.evaluate("dataset_eval_juez")
    print("evaluate OK: revisar Performance del Saved Model")
except Exception as e:
    print(f"WARN evaluate: {e} (revisar guarda de shapes en el log)")
print("OK - verificar Saved Model juez_entity_saved en el Flow")
