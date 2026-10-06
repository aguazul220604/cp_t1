"""Backend webapp Detector PII v3 (consume fase3_modelos, autocontenido).

Carga una vez al arrancar (managed folder del proyecto):
  fase3_modelos/ : vec_A.joblib, modelo_A.joblib, platt_A.joblib, umbral_A.json,
                  vec_B_<aug|base>.joblib, modelo_B_<aug|base>.joblib, clases_B.json
Pipeline por columna (solo `name`, spec v3 MVP v2 §Fase 4):
  name -> name_norm (misma lib que train) -> TF-IDF A -> prob_pii calibrada (Platt)
  -> pii = prob >= umbral_A -> si TRUE, TF-IDF B -> entity/prob_entity
  -> override regex fijo 0.5: si prob_entity<0.5 y regex da 1 match unico, reemplaza.
Endpoint: POST /process_table (1+ archivos .csv/.xlsx, aunque solo traigan
headers) -> JSON columns_analysis con pii/prob + entity/prob_entity.
Sin escritura lateral: no crea ni modifica datasets/folders.
"""
import glob
import json
import os
import re
import traceback
import unicodedata

import dataiku
import joblib
import numpy as np
import pandas as pd
from flask import jsonify, request
from scipy.sparse import hstack

_LOAD_ERROR = None
UMBRAL_ENTITY = 0.5  # fijo arranque (decision Fase 3)


# ---------- normalizacion (copia exacta lib_fase2_normalize.normalize_name) ----------
def _strip_accents(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _split_camel(s):
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    return s


_TRAILING_NUM = re.compile(r"[\s_\-]*\d+\s*$")


def normalize_name(s):
    if s is None:
        return ""
    try:
        if pd.isna(s):
            return ""
    except Exception:
        pass
    s = str(s)
    s = _split_camel(s)
    s = s.lower()
    s = _strip_accents(s)
    s = re.sub(r"[_\-/|;:.]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"(?<=[a-z])(\d+)$", r" \1", s)
    s = re.sub(r"(?<=[a-z])(\d+)(?=\s)", r" \1 ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = _TRAILING_NUM.sub("", s).strip()
    return re.sub(r"\s+", " ", s).strip()


# ---------- regex override (port 1:1 regex.txt, orden especifico->generico) ----------
REGEX_ENTIDADES = [
    ("credenciales_id", [r"soeid", r"geid", r"dispositivo", r"medioacceso", r"tok req"]),
    ("datos_demograficos", [r"numdepend", r"dependientes", r"ocupacion", r"ptrmadre", r"indicadorextranjero"]),
    ("bienes_patrimonio", [r"numautos", r"car dlr"]),
    ("documento_legal", [r"actacons", r"creactecto"]),
    ("fecha_vencimiento", [r"expry", r"exp dt", r"vencim"]),
    ("correo", [r"mail", r"correo"]),
    ("curp", [r"curp"]),
    ("rfc", [r"rfc", r"rf [0-9] d.gitos", r"fiscal"]),
    ("nss", [r"nss", r"seg cli"]),
    ("fecha_nacimiento", [r"nacim", r"edad", r"brthdt"]),
    ("sexo", [r"sexo", r"gndr"]),
    ("apellido", [r"apellido"]),
    ("tarjeta", [r"card", r"crd", r"plastico", r"nucc"]),
    ("telefono", [r"tel", r"cel", r"phone", r"ph no", r"extn", r"ext[0-9]"]),
    ("nomina", [r"nomina", r"numnom", r"numemp", r"empleado"]),
    ("direccion", [r"addr", r"calle", r"colonia", r"colony", r"deleg", r"poblacion",
                   r"nomcol", r"cntry", r"estate", r"city", r"ste bus", r"nacion",
                   r"edo", r"cp", r"zip", r"cveedo", r"nompob"]),
    ("saldo", [r"saldo", r"sdo", r"ingreso", r"bal", r"balance", r"capital",
               r"curr bal", r"tot prin", r"impcasa"]),
    ("credito", [r"cred", r"linea", r"line id", r"linnum", r"limite", r"lmt", r"loan", r"capvig"]),
    ("cliente", [r"clien", r"clnt", r"cust", r"ctenum", r"gfcid", r"user ref"]),
    ("nombre", [r"nombre", r"name", r"nm", r"nm txt", r"razon", r"nom ordenante",
                r"nomcte", r"beneficiario"]),
    ("contrato", [r"contrat", r"contract", r"cto"]),
    ("cuenta", [r"acct", r"account", r"acnt", r"cuenta", r"cta", r"reln"]),
]
_COMPILED = [(e, [re.compile(p, re.IGNORECASE) for p in pats])
             for e, pats in REGEX_ENTIDADES]


def regex_all_matches(name):
    s = str(name or "")
    return [e for e, pats in _COMPILED if any(p.search(s) for p in pats)]


# ---------- carga artefactos fase3 ----------
def _load_artifacts():
    f3 = dataiku.Folder("fase3_modelos").get_path()
    vec_a = joblib.load(os.path.join(f3, "vec_A.joblib"))
    clf_a = joblib.load(os.path.join(f3, "modelo_A.joblib"))
    platt = joblib.load(os.path.join(f3, "platt_A.joblib"))
    umbral_a = 0.05
    ua_path = os.path.join(f3, "umbral_A.json")
    if os.path.exists(ua_path):
        with open(ua_path, encoding="utf-8") as fh:
            umbral_a = float(json.load(fh).get("umbral_A", umbral_a))
    cand = sorted(glob.glob(os.path.join(f3, "vec_B_*.joblib")))
    if not cand:
        raise FileNotFoundError("Falta vec_B_*.joblib en folder fase3_modelos")
    vec_b = joblib.load(cand[0])
    clf_b = joblib.load(cand[0].replace("vec_B_", "modelo_B_"))
    clases = []
    cb_path = os.path.join(f3, "clases_B.json")
    if os.path.exists(cb_path):
        with open(cb_path, encoding="utf-8") as fh:
            clases = list(json.load(fh).get("clases", []))
    return {"vec_a": vec_a, "clf_a": clf_a, "platt": platt,
            "umbral_a": float(umbral_a), "vec_b": vec_b, "clf_b": clf_b,
            "clases": clases,
            "variante_b": os.path.basename(cand[0]).replace("vec_B_", "").replace(".joblib", "")}


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


def _apply_vec(vecs, texts):
    vc, vw = vecs
    return hstack([vc.transform(texts), vw.transform(texts)]).tocsr()


def predict_columns(rows):
    """rows: lista de dicts {source_file, name, dataset, type}. Devuelve lista
    con {source_file, name, is_pii, pii_probability, entity, entity_probability,
    regex_match, override_aplicado}."""
    base = pd.DataFrame(rows)
    names = base["name"].fillna("").astype(str)
    norms = names.map(normalize_name)
    Xa = _apply_vec(ARTS["vec_a"], norms.tolist())
    raw = np.asarray(ARTS["clf_a"].predict_proba(Xa)[:, 1]).ravel()
    try:
        prob = np.asarray(ARTS["platt"].predict_proba(raw.reshape(-1, 1))[:, 1]).ravel()
    except Exception:
        prob = raw
    pii = prob >= float(ARTS["umbral_a"])
    ent = [None] * len(base)
    eprob = [None] * len(base)
    rxdbg = [None] * len(base)
    ovr = [False] * len(base)
    m = np.asarray(pii)
    if int(m.sum()):
        sel = np.where(m)[0]
        Xb = _apply_vec(ARTS["vec_b"], norms.iloc[sel].tolist())
        clf_b = ARTS["clf_b"]
        if hasattr(clf_b, "predict_proba"):
            sb = np.asarray(clf_b.predict_proba(Xb))
            order = list(getattr(clf_b, "classes_", ARTS["clases"]))
            bi = sb.argmax(axis=1)
            for k, i, v in zip(sel, bi, sb.max(axis=1)):
                e_ml = order[int(i)]
                pe = round(float(v), 4)
                matches = regex_all_matches(base["name"].iloc[int(k)])
                if pe < UMBRAL_ENTITY and len(matches) == 1:
                    ent[int(k)] = matches[0]
                    ovr[int(k)] = True
                    rxdbg[int(k)] = matches[0]
                else:
                    ent[int(k)] = e_ml
                    rxdbg[int(k)] = matches[0] if len(matches) == 1 else (
                        None if not matches else "ambiguo")
                eprob[int(k)] = pe
        else:
            pred = clf_b.predict(Xb)
            for k, e_ml in zip(sel, pred):
                matches = regex_all_matches(base["name"].iloc[int(k)])
                ent[int(k)] = e_ml
                rxdbg[int(k)] = matches[0] if len(matches) == 1 else (
                    None if not matches else "ambiguo")
    return [{
        "source_file": r["source_file"],
        "name": r["name"],
        "is_pii": bool(p),
        "pii_probability": round(float(pr), 4),
        "entity": e,
        "entity_probability": ep,
        "regex_match": rx,
        "override_aplicado": bool(o),
    } for r, p, pr, e, ep, rx, o in zip(rows, pii, prob, ent, eprob, rxdbg, ovr)]


@app.route('/process_table', methods=['POST'])
def process_table():
    try:
        if ARTS is None:
            return jsonify({
                "status": "error",
                "message": f"Modelo no cargado. Revisa folder fase3_modelos: {_LOAD_ERROR}",
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
