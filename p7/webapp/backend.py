"""Backend webapp Detector PII v2 (pipeline unificado, autocontenido).

Carga una vez al arrancar (managed folders del proyecto):
  fase5_modelo_operativo/ : modelo.txt, vec_name.pkl, encoders.json (threshold)
  fase2_juez/             : modelo.txt, vectorizer.pkl, clases.json
Endpoint: POST /process_table (1+ archivos .csv/.xlsx, aunque solo traigan
headers) -> JSON columns_analysis con pii/prob + entity/prob_entity.
Sin escritura lateral: no crea ni modifica datasets/folders.
"""
import json
import os
import pickle
import re
import traceback
import unicodedata

import dataiku
import numpy as np
import pandas as pd
from flask import jsonify, request
from scipy.sparse import csr_matrix, hstack

_LOAD_ERROR = None


def _strip_accents(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _norm_light(s):
    if pd.isna(s):
        return ""
    return re.sub(r"\s+", " ", _strip_accents(str(s).lower())).strip()


def _softmax(scores):
    scores = np.asarray(scores, dtype=float)
    if scores.ndim == 1:
        scores = np.vstack([1 - scores, scores]).T
    if not np.allclose(scores.sum(axis=1), 1.0, atol=1e-3):
        e = np.exp(scores - scores.max(axis=1, keepdims=True))
        scores = e / e.sum(axis=1, keepdims=True)
    return scores


def _load_artifacts():
    import lightgbm as lgb

    f5 = dataiku.Folder("fase5_modelo_operativo").get_path()
    f2 = dataiku.Folder("fase2_juez").get_path()
    with open(os.path.join(f5, "vec_name.pkl"), "rb") as f:
        vec_name = pickle.load(f)
    with open(os.path.join(f5, "encoders.json"), encoding="utf-8") as f:
        enc = json.load(f)
    with open(os.path.join(f2, "vectorizer.pkl"), "rb") as f:
        j_vec = pickle.load(f)
    with open(os.path.join(f2, "clases.json"), encoding="utf-8") as f:
        j_clases = json.load(f)
    return {
        "vec_name": vec_name,
        "threshold": float(enc.get("threshold", 0.75)),
        "te_map": enc["te_map"],
        "te_global": float(enc["te_global"]),
        "top_types": list(enc["top_types"]),
        "clf": lgb.Booster(model_file=os.path.join(f5, "modelo.txt")),
        "j_vec": j_vec,
        "j_clases": j_clases,
        "j_bst": lgb.Booster(model_file=os.path.join(f2, "modelo.txt")),
    }


try:
    ARTS = _load_artifacts()
except Exception as exc:  # visible en logs + respuesta 500 explicita
    ARTS = None
    _LOAD_ERROR = f"{type(exc).__name__}: {exc}"
    traceback.print_exc()


def read_uploaded_file(file):
    filename = file.filename.lower()
    if filename.endswith(".csv"):
        return pd.read_csv(file)
    elif filename.endswith((".xls", ".xlsx")):
        return pd.read_excel(file)
    else:
        raise ValueError(f"Formato no soportado para '{file.filename}'. Sube archivos .csv o .xlsx.")


def predict_columns(rows):
    """rows: lista de dicts {source_file, name, dataset, type}. Devuelve lista
    con {source_file, name, is_pii, pii_probability, entity, entity_probability}."""
    base = pd.DataFrame(rows)
    key = base["name"].map(_norm_light)
    longitud = base["name"].fillna("").astype(str).str.len().values
    Xn = ARTS["vec_name"].transform(key.fillna("").tolist())
    te = base["dataset"].map(ARTS["te_map"]).fillna(ARTS["te_global"]).values
    top = ARTS["top_types"]
    s = base["type"].fillna("").where(base["type"].isin(top), "OTROS")
    typ = pd.get_dummies(s, prefix="typ").reindex(
        columns=["typ_" + t for t in top] + ["typ_OTROS"],
        fill_value=0).astype(np.int8).values
    num = np.vstack([longitud, np.zeros(len(base)), te]).T
    X = hstack([Xn, csr_matrix(num), csr_matrix(typ)]).tocsr()
    prob = np.asarray(ARTS["clf"].predict(X)).ravel()
    pii = prob >= ARTS["threshold"]
    ent = [None] * len(base)
    eprob = [None] * len(base)
    m = (key != "").to_numpy() & np.asarray(pii)
    if int(m.sum()):
        sel = np.where(m)[0]
        Xj = ARTS["j_vec"].transform(key.iloc[sel].tolist())
        sj = _softmax(np.asarray(ARTS["j_bst"].predict(Xj)))
        idx = sj.argmax(axis=1)
        for k, i, v in zip(sel, idx, sj.max(axis=1)):
            ent[int(k)] = ARTS["j_clases"][int(i)]
            eprob[int(k)] = round(float(v), 4)
    return [{
        "source_file": r["source_file"],
        "name": r["name"],
        "is_pii": bool(p),
        "pii_probability": round(float(pr), 4),
        "entity": e,
        "entity_probability": ep,
    } for r, p, pr, e, ep in zip(rows, pii, prob, ent, eprob)]


@app.route('/process_table', methods=['POST'])
def process_table():
    try:
        if ARTS is None:
            return jsonify({
                "status": "error",
                "message": f"Modelo no cargado. Revisa folders/artifacts: {_LOAD_ERROR}",
            }), 500

        files = request.files.getlist('file')
        if not files:
            return jsonify({"status": "error", "message": "No se subió ningún archivo."}), 400

        rows, skipped = [], []
        for file in files:
            if file.filename == "":
                continue
            try:
                df = read_uploaded_file(file)
            except ValueError as ve:
                skipped.append(str(ve))
                continue
            if df.shape[1] == 0:
                skipped.append(f"'{file.filename}' no tiene columnas para analizar.")
                continue
            for col_name in df.columns:
                col_str = str(col_name).strip()
                if not col_str or col_str.lower() == "nan":
                    continue
                rows.append({
                    "source_file": file.filename,
                    "name": col_str,
                    "dataset": file.filename,
                    "type": str(df[col_name].dtype),
                })

        if not rows:
            return jsonify({
                "status": "error",
                "message": " | ".join(skipped) if skipped else "Ningún archivo pudo procesarse.",
            }), 400

        response = {"status": "success", "columns_analysis": predict_columns(rows)}
        if skipped:
            response["warnings"] = skipped
        return jsonify(response)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
