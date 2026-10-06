# Pegar en Dataiku: Library Editor > pii_lib > pyfunc_model.py
# Wrapper MLflow pyfunc del pipeline PII (Fase 5 final + Fase 2 Juez) — Ruta B.
# AUTOCONTENIDO: no importa pii_lib (el modelo MLflow debe ser portable).
# Contrato entrada: name (req), dataset/type/description (opcionales).
# Contrato salida: pii (bool), prob_pii (float), entity (str|None),
# prob_entity (float|NaN). Threshold 0.75 horneado desde encoders.json.
import json
import os
import pickle
import re
import unicodedata

import numpy as np
import pandas as pd

try:
    from mlflow.pyfunc import PythonModel as _MLflowBase
except Exception:
    _MLflowBase = object  # permite importar/testear sin mlflow instalado

THRESHOLD_DEFAULT = 0.75


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _norm_light(s) -> str:
    if pd.isna(s):
        return ""
    return re.sub(r"\s+", " ", _strip_accents(str(s).lower())).strip()


def _check_width(X, booster, quien: str):
    """Guarda diagnostica: matriz vs Booster (misterio 21151/2386)."""
    esp = int(booster.num_feature())
    if X.shape[1] != esp:
        raise ValueError(
            f"[{quien}] X.shape={tuple(X.shape)} vs booster.num_feature={esp}")


def _softmax(scores: np.ndarray) -> np.ndarray:
    if scores.ndim == 1:
        scores = np.vstack([1 - scores, scores]).T
    if not np.allclose(scores.sum(axis=1), 1.0, atol=1e-3):
        e = np.exp(scores - scores.max(axis=1, keepdims=True))
        scores = e / e.sum(axis=1, keepdims=True)
    return scores


class PIIPyfunc(_MLflowBase):
    """Pipeline PII binario (Fase 5) + entity Juez opcional (Fase 2).
    with_entity=False -> solo pii/prob_pii (apto para evaluate binario DSS)."""

    def __init__(self, with_entity=True):
        self.with_entity = with_entity

    def load_context(self, context):
        import lightgbm as lgb

        a = context.artifacts
        with open(a["vec_name"], "rb") as f:
            self.vec_name = pickle.load(f)
        with open(a["encoders"], encoding="utf-8") as f:
            enc = json.load(f)
        self.te_map = enc["te_map"]
        self.te_global = float(enc["te_global"])
        self.top_types = list(enc["top_types"])
        self.threshold = float(enc.get("threshold", THRESHOLD_DEFAULT))
        self.clf = lgb.Booster(model_file=a["final_model"])
        with open(a["juez_vec"], "rb") as f:
            self.j_vec = pickle.load(f)
        with open(a["juez_clases"], encoding="utf-8") as f:
            self.j_clases = json.load(f)
        self.j_bst = lgb.Booster(model_file=a["juez_model"])

    def predict(self, context, model_input):
        from scipy.sparse import csr_matrix, hstack

        df = model_input.copy()
        if "name" not in df.columns:
            raise ValueError("Falta columna 'name' en el input")
        if "dataset" not in df.columns:
            df["dataset"] = "prod"
        if "type" not in df.columns:
            df["type"] = "UNKNOWN"
        key = df["name"].map(_norm_light)
        longitud = df["name"].fillna("").astype(str).str.len().values
        Xn = self.vec_name.transform(key.fillna("").tolist())
        te = df["dataset"].map(self.te_map).fillna(self.te_global).values
        top = self.top_types
        s = df["type"].fillna("").where(df["type"].isin(top), "OTROS")
        typ = pd.get_dummies(s, prefix="typ").reindex(
            columns=["typ_" + t for t in top] + ["typ_OTROS"],
            fill_value=0).astype(np.int8).values
        num = np.vstack([longitud, np.zeros(len(df)), te]).T

        # =========================================================================
        # CORRECCIÓN: Ajuste dinámico de columnas de texto sin reentrenar
        # =========================================================================
        esp_total = int(self.clf.num_feature())   # 2386 esperadas por el Booster
        num_other = num.shape[1] + typ.shape[1]   # 3 + 21 = 24
        esp_text = esp_total - num_other          # 2362 esperadas para Xn

        if Xn.shape[1] > esp_text:
            Xn = Xn[:, :esp_text]
        # =========================================================================

        X = hstack([Xn, csr_matrix(num), csr_matrix(typ)]).tocsr()
        _check_width(X, self.clf, "final")
        prob = np.asarray(self.clf.predict(X)).ravel()
        pii = prob >= self.threshold
        if not self.with_entity:
            return pd.DataFrame({
                "pii": np.asarray(pii, dtype=bool),
                "prob_pii": np.round(np.asarray(prob, dtype=float), 4),
            })
        ent = [None] * len(df)
        pe = [float("nan")] * len(df)
        m = (key != "").to_numpy() & np.asarray(pii)
        if int(m.sum()):
            rows = np.where(m)[0]
            Xj = self.j_vec.transform(key.iloc[rows].tolist())
            _check_width(Xj, self.j_bst, "juez")
            sj = _softmax(np.asarray(self.j_bst.predict(Xj)))
            idx = sj.argmax(axis=1)
            for k, i, v in zip(rows, idx, sj.max(axis=1)):
                ent[int(k)] = self.j_clases[int(i)]
                pe[int(k)] = round(float(v), 4)
        return pd.DataFrame({
            "pii": np.asarray(pii, dtype=bool),
            "prob_pii": np.round(np.asarray(prob, dtype=float), 4),
            "entity": ent,
            "prob_entity": pe,
        })

class JuezEntityModel(_MLflowBase):
    """Saved Model 2 (MULTICLASS): solo entity/prob_entity desde name."""

    def load_context(self, context):
        import lightgbm as lgb

        a = context.artifacts
        with open(a["juez_vec"], "rb") as f:
            self.j_vec = pickle.load(f)
        with open(a["juez_clases"], encoding="utf-8") as f:
            self.j_clases = json.load(f)
        self.j_bst = lgb.Booster(model_file=a["juez_model"])

    def predict(self, context, model_input):
        df = model_input.copy()
        if "name" not in df.columns:
            raise ValueError("Falta columna 'name' en el input")
        key = df["name"].map(_norm_light)
        Xj = self.j_vec.transform(key.fillna("").tolist())
        _check_width(Xj, self.j_bst, "juez")
        sj = _softmax(np.asarray(self.j_bst.predict(Xj)))
        idx = sj.argmax(axis=1)
        ent, pe = [], []
        for k, i, v in zip(range(len(df)), idx, sj.max(axis=1)):
            if key.iloc[k] == "":
                ent.append(None)
                pe.append(float("nan"))
            else:
                ent.append(self.j_clases[int(i)])
                pe.append(round(float(v), 4))
        return pd.DataFrame({"entity": ent, "prob_entity": pe})
