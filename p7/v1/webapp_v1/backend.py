"""
Backend webapp Detector PII v5 FINAL (binario v3 solo-name + Juez 23, híbrido optimizado).

Carga una vez al arrancar desde las carpetas gestionadas en Dataiku:
  fase5_modelo_v3/ : modelo.txt (LightGBM), vec_name.pkl, encoders.json
  fase2_juez_v3/   : modelo.txt, vectorizer.pkl, clases.json (23), calibrador.pkl

Jerarquía de Decisión:
  Nivel 1 EXACTO  : Coincidencia directa en lista canónica -> PII forzado.
  Nivel 2 RARO    : Abreviaturas bancarias y slang corporativo -> PII forzado.
  Nivel 3 MODELO  : Probabilidad estadística del modelo ML >= THRESHOLD (0.667).
  Nivel 4 FUZZY   : PISO (0.15) <= prob < THRESHOLD + keyword de rescate.
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

# --- Funciones Auxiliares de Normalización ---

def _strip_accents(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", str(s))
        if unicodedata.category(c) != "Mn"
    )

def _norm_light(s):
    if pd.isna(s):
        return ""
    return re.sub(r"\s+", " ", _strip_accents(str(s).lower())).strip()

def _name_norm(s):
    return re.sub(r"\s*\d+$", "", _norm_light(s)).strip()

def _softmax(scores):
    scores = np.asarray(scores, dtype=float)
    if scores.ndim == 1:
        scores = np.vstack([1 - scores, scores]).T
    if not np.allclose(scores.sum(axis=1), 1.0, atol=1e-3):
        e = np.exp(scores - scores.max(axis=1, keepdims=True))
        scores = e / e.sum(axis=1, keepdims=True)
    return scores

# --- Configuración de Umbrales y Probabilidades ---

THRESHOLD = 0.667       # Umbral binario PII principal
PISO_RESCATE = 0.15    # Umbral mínimo para activar rescate fuzzy
UMBRAL_FALLBACK = 0.50  # Si la certidumbre del Juez es baja (<0.50), interviene la regla

PROB_REGLA = {"exacto": 0.95, "raro": 0.90, "fuzzy": 0.80}
PROB_ENT_REGLA = 0.90

# --- Mapeos y Reglas Deterministas ---

_REGLAS_FALLBACK = [
    ("curp", ("curp",)),
    ("rfc", ("rfc",)),
    ("nss", ("nss", "seguro_social", "imss", "seg_social")),
    ("correo", ("correo", "email", "mail")),
    ("sexo", ("sexo", "genero")),
    ("fecha_vencimiento", ("venc", "expira", "expiry", "vigencia", "f_venc")),
    ("fecha_nacimiento", ("nacim", "fnacim", "birth", "f_nac")),
    ("telefono", ("tel", "cel", "fono", "phone")),
    ("tarjeta", ("tarjeta", "plastico", "card", "crd")),
    ("cuenta", ("cuenta", "acct", "cta", "ctogru", "aper cte", "aper_cte")),
    ("cliente", ("cliente", "cust", "clnt", "borrower")),
]

def _fallback_regla(key_light, clases):
    k = " " + (key_light or "").replace("_", " ") + " "
    validas = set(clases or [])
    for ent, kws in _REGLAS_FALLBACK:
        if ent in validas and any(kw in k for kw in kws):
            return ent
    return None

_EXACTOS_FUERZA = {
    # Nombres Canónicos Banamex y Sufijos Comunes
    "cliente", "correo", "telefono", "contrato", "direccion", "rfc",
    "nomina", "saldo", "cuenta", "nombre", "soeid", "credito",
    "fecha vencimiento", "fecha nacimiento", "sexo", "apellido", "curp",
    "nss", "tarjeta", "actacons", "numdepend", "numautos",
    "crd acct nbr", "aper cte016", "aper cte", "apertura cuenta",
    "fecha venc", "fecha nac", "ap paterno", "ap materno",
    "num dependientes", "num autos",
}

_TYPOS = {
    "direcion": "direccion",
    "direccin": "direccion",
    "dirreccion": "direccion",
    "correoo": "correo",
    "correro": "correo",
    "apelldio": "apellido",
    "apeillido": "apellido",
    "fehca vencimiento": "fecha vencimiento",
    "fehca nacimiento": "fecha nacimiento",
    "tellefono": "telefono",
    "trajeta": "tarjeta",
    "cuenat": "cuenta",
    "nomre": "nombre",
    "contratto": "contrato",
}

_RAROS_FUERZA = [
    ("credenciales_id", ("soeid", "geid", "efirma", "firma elec"), ()),
    ("bienes_patrimonio", ("numautos", "car dlr", "cardlr"), ()),
    ("datos_demograficos", ("numdepend", "dependientes"), ()),
    ("documento_legal", ("actacons", "creactecto"), ()),
    ("tarjeta", ("crd acct nbr", "crd", "plastico"), ("ordenante",)),
    ("cuenta", ("acct nbr", "acct", "aper cte", "aper_cte"), ("crd",)),
    ("nss", ("nss", "imss"), ()),
    ("curp", ("curp",), ()),
    ("rfc", ("rfc",), ()),
]

def _corrige_typo(key_light):
    k = (key_light or "").replace("_", " ").strip()
    if k in _TYPOS:
        return _TYPOS[k]
    if k in _EXACTOS_FUERZA:
        return k
    return k

def _es_exacto_fuerza(key_light):
    k = _corrige_typo(key_light)
    return k in _EXACTOS_FUERZA

def _raro_fuerza(key_light):
    k = " " + _corrige_typo(key_light) + " "
    for ent, pos, anti in _RAROS_FUERZA:
        if anti and any(a in k for a in anti):
            continue
        if any(p in k for p in pos):
            return ent
    return None

_REGLAS_RESCATE = [
    ("nss", ("nss", "seguridad_imss", "seg_social", "imss"), ()),
    ("curp", ("curp",), ()),
    ("rfc", ("rfc",), ()),
    ("apellido", ("apellido", "ap_paterno", "ap_materno", "paterno", "materno",
                  "surname", "last_name"), ()),
    ("fecha_nacimiento", ("nacim", "fnac", "fnacim", "birth", "dob"),
     ("venc", "expira", "expiry", "vigencia", "ordenante")),
    ("fecha_vencimiento", ("venc", "expira", "expiry", "vigencia", "f_venc"),
     ("nacim", "fnac", "birth")),
    ("credenciales_id", ("soeid", "geid", "password", "passwd", "pwd", "token",
                         "login", "credencial", "firma_elec", "efirma"), ()),
    ("documento_legal", ("acta", "actacons", "escritura", "poder_notarial",
                         "amparo", "demanda", "pasaporte", "licencia",
                         "cedula", "cartilla"), ()),
    ("datos_demograficos", ("numdepend", "dependientes", "ocupacion",
                            "estado_civil", "nacionalidad", "demograf"), ()),
    ("correo", ("correo", "email", "mail"), ("sucursal",)),
    ("sexo", ("sexo", "genero"), ()),
    ("bienes_patrimonio", ("inmueble", "patrimonio", "hipoteca", "avaluo",
                           "predial", "vehiculo", "numautos", "car dlr",
                           "cardlr"), ()),
    ("tarjeta", ("tarjeta", "plastico", "card", "crd"), ()),
    ("telefono", ("telefono", "tel_casa", "tel_oficina", "cel", "phone"), ()),
    ("cuenta", ("cuenta", "cuentabasica", "cta", "ctogru", "ordenante",
                 "account", "aper cte", "aper_cte"), ()),
    ("nomina", ("nomina", "nominamaker"), ()),
    ("nombre", ("nombre",), ("nomina", "nominamaker")),
    ("cliente", ("cliente", "cust", "clnt", "borrower"), ()),
    ("contrato", ("contrato", "contract"), ()),
    ("credito", ("credito", "credit", "loan"), ()),
    ("saldo", ("saldo", "sdo"), ()),
    ("direccion", ("direccion", "direcion", "colonia", "municipio",
                    "alcaldia", "entidad_federativa", "codigo_postal",
                    "calle", "deleg", "addr", "poblacion", "nomcol",
                    "cntry", "estate", "city"),
     ()),
]

def _rescate_regex(key_light):
    k = " " + (key_light or "").replace("_", " ") + " "
    for ent, pos, anti in _REGLAS_RESCATE:
        if anti and any(a.replace("_", " ") in k for a in anti):
            continue
        if any(p.replace("_", " ") in k for p in pos):
            return ent
    return None

# --- Control de Dimensiones de Matriz ---

def _check_width_bin(X, clf):
    esp = int(clf.num_feature())
    if X.shape[1] > esp:
        return X[:, :esp]
    if X.shape[1] != esp:
        raise ValueError(
            f"[binario] X.shape={tuple(X.shape)} vs booster.num_feature={esp}. "
            "Despliega vec_name.pkl + modelo.txt juntos desde fase5_modelo_v3.")
    return X

def _check_width_juez(Xj, j_bst):
    esp = int(j_bst.num_feature())
    if Xj.shape[1] > esp:
        return Xj[:, :esp]
    if Xj.shape[1] != esp:
        raise ValueError(
            f"[juez] Xj.shape={tuple(Xj.shape)} vs booster.num_feature={esp}. "
            "Despliega vectorizer.pkl + modelo.txt + clases.json juntos desde fase2_juez_v3.")
    return Xj

# --- Carga de Artefactos ---

def _load_artifacts():
    import lightgbm as lgb

    try:
        f5 = dataiku.Folder("fase5_modelo_v3").get_path()
    except Exception:
        f5 = dataiku.Folder("fase5_modelo_operativo").get_path()

    f2 = dataiku.Folder("fase2_juez_v3").get_path()

    with open(os.path.join(f5, "vec_name.pkl"), "rb") as f:
        vec_name = pickle.load(f)
    with open(os.path.join(f5, "encoders.json"), encoding="utf-8") as f:
        enc = json.load(f)
    with open(os.path.join(f2, "vectorizer.pkl"), "rb") as f:
        j_vec = pickle.load(f)
    with open(os.path.join(f2, "clases.json"), encoding="utf-8") as f:
        j_clases = json.load(f)

    cal_path = os.path.join(f2, "calibrador.pkl")
    j_cal = None
    if os.path.exists(cal_path):
        with open(cal_path, "rb") as f:
            j_cal = pickle.load(f)

    return {
        "vec_name": vec_name,
        "threshold": THRESHOLD,
        "num_cols": list(enc.get("num_cols", ["longitud", "n_tokens", "tiene_sufijo"])),
        "clf": lgb.Booster(model_file=os.path.join(f5, "modelo.txt")),
        "j_vec": j_vec,
        "j_clases": j_clases,
        "j_bst": lgb.Booster(model_file=os.path.join(f2, "modelo.txt")),
        "j_cal": j_cal,
    }

try:
    ARTS = _load_artifacts()
except Exception as exc:
    ARTS = None
    _LOAD_ERROR = f"{type(exc).__name__}: {exc}"
    traceback.print_exc()

# --- Lectura de Archivos ---

def read_uploaded_file(file):
    filename = file.filename.lower()
    if filename.endswith(".csv"):
        return pd.read_csv(file)
    elif filename.endswith((".xls", ".xlsx")):
        return pd.read_excel(file)
    else:
        raise ValueError(f"Formato no soportado para '{file.filename}'. Sube archivos .csv o .xlsx.")

# --- Lógica Principal de Inferencia ---

def predict_columns(rows):
    base = pd.DataFrame(rows)
    key = base["name"].map(_norm_light)
    norms = base["name"].map(_name_norm)

    feats = {
        "longitud": base["name"].fillna("").astype(str).str.len().values,
        "n_tokens": norms.str.split().str.len().fillna(0).astype(int).values,
        "tiene_sufijo": key.str.contains(r"\d+$", regex=True).astype(int).values,
    }

    Xn = ARTS["vec_name"].transform(key.fillna("").tolist())
    num = np.vstack([feats[c] for c in ARTS["num_cols"]]).T
    X = _check_width_bin(hstack([Xn, csr_matrix(num)]).tocsr(), ARTS["clf"])

    prob = np.asarray(ARTS["clf"].predict(X)).ravel()
    pii = prob >= ARTS["threshold"]
    prob_final = np.asarray(prob, dtype=float).copy()
    keys_list = [_corrige_typo(k) for k in key.fillna("").tolist()]
    prior_ent = [None] * len(base)
    motivo = ["modelo" if p else "" for p in pii]

    c_exact = c_raro = c_fuzzy = 0

    # Rescate por Reglas (Capas 1, 2 y 4)
    for i, (pr, k) in enumerate(zip(prob, keys_list)):
        if not k:
            continue
        if pii[i]:
            continue
        if _es_exacto_fuerza(k):
            pii[i] = True
            prior_ent[i] = _rescate_regex(k) or _fallback_regla(k, ARTS["j_clases"])
            motivo[i] = "exacto"
            prob_final[i] = max(float(pr), PROB_REGLA["exacto"])
            c_exact += 1
        elif _raro_fuerza(k) is not None:
            pii[i] = True
            prior_ent[i] = _raro_fuerza(k)
            motivo[i] = "raro"
            prob_final[i] = max(float(pr), PROB_REGLA["raro"])
            c_raro += 1
        elif PISO_RESCATE <= float(pr) < ARTS["threshold"]:
            r = _rescate_regex(k)
            if r is not None:
                pii[i] = True
                prior_ent[i] = r
                motivo[i] = "fuzzy"
                prob_final[i] = max(float(pr), PROB_REGLA["fuzzy"])
                c_fuzzy += 1

    print(f"[binario-v5] thr={ARTS['threshold']} piso={PISO_RESCATE} "
          f"pii_modelo={int((prob >= ARTS['threshold']).sum())} "
          f"exacto={c_exact} raro={c_raro} fuzzy={c_fuzzy} de {len(base)}")

    # Determinación de la Entidad (Juez)
    ent = [None] * len(base)
    eprob = [None] * len(base)
    m = (key != "").to_numpy() & np.asarray(pii)

    if int(m.sum()):
        sel = np.where(m)[0]
        keys = key.iloc[sel].tolist()
        Xj = ARTS["j_vec"].transform(keys)
        Xj = _check_width_juez(Xj, ARTS["j_bst"])

        if ARTS.get("j_cal") is not None:
            sj = np.asarray(ARTS["j_cal"].predict_proba(Xj), dtype=float)
        else:
            sj = _softmax(np.asarray(ARTS["j_bst"].predict(Xj)))

        idx = sj.argmax(axis=1)
        for j, (k, i_cls, v) in enumerate(zip(sel, idx, sj.max(axis=1))):
            e = ARTS["j_clases"][int(i_cls)]
            p = round(float(v), 4)
            mot = motivo[int(k)]
            pr = prior_ent[int(k)]
            valid = ARTS["j_clases"] or []

            if mot in ("exacto", "raro") and pr is not None and pr in valid:
                e = pr
                p = round(max(float(v), PROB_ENT_REGLA), 4)
            elif p < UMBRAL_FALLBACK:
                fb = _fallback_regla(keys[j], ARTS["j_clases"])
                if pr is not None and pr in valid:
                    e = pr
                    p = round(max(float(v), PROB_ENT_REGLA), 4)
                elif fb is not None:
                    e = fb
                    p = round(max(float(v), 0.8000), 4)

            ent[int(k)] = e
            eprob[int(k)] = p

    return [{
        "source_file": r["source_file"],
        "name": r["name"],
        "is_pii": bool(p),
        "pii_probability": round(float(pr), 4),
        "entity": e,
        "entity_probability": ep,
    } for r, p, pr, e, ep in zip(rows, pii, prob_final, ent, eprob)]

# --- Endpoint Flask ---

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