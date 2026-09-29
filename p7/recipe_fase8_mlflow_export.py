# Dataiku Python recipe: fase8_mlflow_export (Ruta B -> Saved Model)
# Inputs (Flow):  dataset_entrenamiento_final + folders fase5_modelo_operativo,
#                 fase2_juez
# Outputs (Flow): dataset_eval_holdout + folder mlflow_tmp (modelo MLflow)
# + crea/actualiza programaticamente el Saved Model pii_lgbm_saved
#   (MLFLOW_PYFUNC, BINARY_CLASSIFICATION, threshold operativo 0.75).
# Requiere mlflow en el code env. CODE_ENV: verificar en Admin > Code envs.
import json
import os
import shutil

import dataiku
import mlflow
import numpy as np
import pandas as pd
from pii_lib.normalize import join_key
from pii_lib.pyfunc_model import PIIPyfunc
from sklearn.model_selection import train_test_split

CODE_ENV = "CodeEnv39CleanProjects"  # <-- VERIFICAR nombre exacto del code env
SAVED_MODEL_NAME = "pii_lgbm_saved"
SEED = 0

df = dataiku.Dataset("dataset_entrenamiento_final").get_dataframe().reset_index(drop=True)

# ---- holdout honesto (mismo split por key, SEED=0 de Fase 5) ----
key_lab = df.groupby("key")["pii_final"].apply(
    lambda s: int(s.astype(bool).mean() >= 0.5))
ukeys = key_lab.index.to_numpy()
ktr, kva = train_test_split(ukeys, test_size=0.20,
                            stratify=key_lab.values, random_state=SEED)
eva = df[df["key"].isin(kva)].reset_index(drop=True)
dataiku.Dataset("dataset_eval_holdout").write_with_schema(eva)
print(f"eval={len(eva)} (keys={len(kva)})")

# ---- modelo MLflow ----
f5 = dataiku.Folder("fase5_modelo_operativo").get_path()
f2 = dataiku.Folder("fase2_juez").get_path()
model_dir = os.path.join(dataiku.Folder("mlflow_tmp").get_path(), "pii_model")
shutil.rmtree(model_dir, ignore_errors=True)
mlflow.pyfunc.save_model(
    path=model_dir,
    python_model=PIIPyfunc(),
    artifacts={
        "final_model": os.path.join(f5, "modelo.txt"),
        "vec_name": os.path.join(f5, "vec_name.pkl"),
        "encoders": os.path.join(f5, "encoders.json"),
        "juez_model": os.path.join(f2, "modelo.txt"),
        "juez_vec": os.path.join(f2, "vectorizer.pkl"),
        "juez_clases": os.path.join(f2, "clases.json"),
    },
    pip_requirements=["scikit-learn", "lightgbm", "pandas", "numpy", "scipy"],
)
print("MLflow model guardado en mlflow_tmp/pii_model")

# ---- Saved Model (crear si no existe) ----
client = dataiku.api_client()
project = client.get_project(dataiku.default_project_key())
sm = None
for item in project.list_saved_models():
    info = item if isinstance(item, dict) else item.get_settings().get_raw()
    if info.get("name") == SAVED_MODEL_NAME:
        sm = project.get_saved_model(info.get("id"))
        break
if sm is None:
    sm = project.create_mlflow_pyfunc_model(SAVED_MODEL_NAME, "BINARY_CLASSIFICATION")
    print(f"Saved Model creado: {SAVED_MODEL_NAME}")
else:
    print(f"Saved Model existente: {SAVED_MODEL_NAME}")

try:
    n_ver = len(sm.list_versions())
except Exception:
    n_ver = 0
vid = f"v{n_ver + 1}"
try:
    ver = sm.import_mlflow_version_from_managed_folder(
        vid, "mlflow_tmp", "pii_model", CODE_ENV,
        binary_classification_threshold=0.75)
except TypeError:
    ver = sm.import_mlflow_version_from_managed_folder(
        vid, "mlflow_tmp", "pii_model", CODE_ENV)
print(f"version importada: {vid}")

try:
    ver.set_core_metadata("pii_final", ["False", "True"], "dataset_eval_holdout")
except Exception as e:
    print(f"WARN set_core_metadata: {e}")
try:
    ver.evaluate("dataset_eval_holdout")
    print("evaluate OK: revisar pestana Performance del Saved Model")
except Exception as e:
    print(f"WARN evaluate (si es por columnas extra -> contingencia 2 modelos): {e}")
print("OK - verificar Saved Model pii_lgbm_saved en el Flow")
