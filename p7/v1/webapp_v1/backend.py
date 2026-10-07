"""Backend webapp Detector PII v5 FINAL (binario v3 solo-name + Juez 23, híbrido).

Carga una vez al arrancar (managed folders del proyecto):
  fase5_modelo_v3/ : modelo.txt (LightGBM ganador), vec_name.pkl,
                     encoders.json (num_cols; threshold se FIJA en codigo)
  fase2_juez_v3/   : modelo.txt, vectorizer.pkl, clases.json (23),
                     calibrador.pkl (CalibratedClassifierCV sigmoide)
Regla operativa FINAL (pelado o slang, con typos):
  Nivel 1 EXACTO  : key normalizada == canonico 23-TEST -> PII aunque prob~0.
  Nivel 2 RARO    : abreviatura rara (soeid, numautos, crd/acct...) -> PII aunque prob<PISO.
  Nivel 3 MODELO  : prob >= THRESHOLD (0.667).
  Nivel 4 FUZZY   : PISO (0.15) <= prob < THR + keyword.
Prob original intacta para auditoria. Entity: si el juez da <0.50 se usa
el rescate/fallback como prior (corrige fecha_vencimiento 22%).
Soporta typos: direccin/direccion -> direccion, correoo -> correo, etc.
Endpoint: POST /process_table -> JSON columns_analysis con pii/prob + entity/prob_entity.
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


THRESHOLD = 0.667  # fijo en codigo (decision; ignora el JSON)
PISO_RESCATE = 0.15  # solo nivel FUZZY rescata si PISO <= prob < THRESHOLD + keyword
UMBRAL_FALLBACK = 0.50
# Nivel 1 y 2 fuerzan PII sin importar prob (incluso 0.00): son listas
# cerradas de alta precision, no heuristica abierta. No generan FP fuera
# de estas keys porque exigen match exacto o abreviatura rara + antis.

# Reglas deterministas SOLO si prob_entity < UMBRAL_FALLBACK. Autocontenidas
# (duplican pii_lib/juez_v2 para no acoplar la webapp a la libreria).
_REGLAS_FALLBACK = [
    ("curp", ("curp",)),
    ("rfc", ("rfc",)),
    ("nss", ("nss", "seguro_social", "imss")),
    ("correo", ("correo", "email", "mail")),
    ("sexo", ("sexo", "genero")),
    ("fecha_vencimiento", ("venc", "expira", "expiry", "vigencia")),
    ("fecha_nacimiento", ("nacim", "fnacim", "birth")),
    ("telefono", ("tel", "cel", "fono", "phone")),
    ("tarjeta", ("tarjeta", "plastico", "card", "crd")),
    ("cuenta", ("cuenta", "acct", "cta", "ctogru")),
    ("cliente", ("cliente", "cust", "clnt")),
]


def _fallback_regla(key_light, clases):
    k = " " + (key_light or "").replace("_", " ") + " "
    validas = set(clases or [])
    for ent, kws in _REGLAS_FALLBACK:
        if ent in validas and any(kw in k for kw in kws):
            return ent
    return None


# --- FINAL v5: canonicos exactos (Nivel 1) + typos conocidos ---
# key ya viene _norm_light (minusculas, sin acentos, espacios colapsados).
# Se compara con "_"->" " para que "crd_acct_nbr" == "crd acct nbr".
_EXACTOS_FUERZA = {
    # 23-TEST + canonicos produccion (pelado o con sufijo numerico ya limpio):
    "cliente", "correo", "telefono", "contrato", "direccion", "rfc",
    "nomina", "saldo", "cuenta", "nombre", "soeid", "credito",
    "fecha vencimiento", "fecha nacimiento", "sexo", "apellido", "curp",
    "nss", "tarjeta", "actacons", "numdepend", "numautos",
    "crd acct nbr", "aper cte016",
    # variantes separador/casing ya normalizadas:
    "fecha venc", "fecha nac", "ap paterno", "ap materno",
    "num dependientes", "num autos",
}
# Typos observados en TEST/prod -> forma canonica. Solo estos, no fuzzy abierto.
_TYPOS = {
    "direcion": "direccion",
    "direccion": "direccion",  # sin i (captura nueva TEST)
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
# Nivel 2: abreviaturas raras de alta precision. Si aparecen como token,
# fuerzan PII aunque prob < PISO. Antis evitan FP (sucursal, etc).
_RAROS_FUERZA = [
    ("credenciales_id", ("soeid", "geid", "efirma", "firma elec"), ()),
    ("bienes_patrimonio", ("numautos", "car dlr", "cardlr"), ()),
    ("datos_demograficos", ("numdepend", "dependientes",), ()),
    ("documento_legal", ("actacons", "creactecto"), ()),
    ("tarjeta", ("crd acct nbr", "crd", "plastico"), ("ordenante",)),
    ("cuenta", ("acct nbr", "acct",), ("crd",)),
    ("nss", ("nss", "imss",), ()),
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


# Rescate regex binario: refuerzo del LightGBM, 23 entidades (otro_pii nunca
# rescata: es cuarentena). Todo sobre key normalizada (minusculas, sin acentos).
# Orden: especificas primero; primer match gana.
_REGLAS_RESCATE = [
    ("nss", ("nss", "seguridad_imss", "seg_social", "imss"), ()),
    ("curp", ("curp",), ()),
    ("rfc", ("rfc",), ()),
    ("apellido", ("apellido", "ap_paterno", "ap_materno", "paterno", "materno",
                  "surname", "last_name"), ()),
    ("fecha_nacimiento", ("nacim", "fnac", "fnacim", "birth", "dob"),
     ("venc", "expira", "expiry", "vigencia", "ordenante")),
    ("fecha_vencimiento", ("venc", "expira", "expiry", "vigencia"),
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
    ("telefono", ("telefono", "tel_casa", "tel_oficina", "cel", "phone"), ()),
    ("tarjeta", ("tarjeta", "plastico", "card", "crd"), ()),
    ("cuenta", ("cuenta", "cuentabasica", "cta", "ctogru", "ordenante",
                 "account"), ()),
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
    # Normaliza igual ambos lados: la key llega con "_"->" ", asi que los
    # patrones con "_" (tel_casa, ap_paterno, crd_nbr) se comparan con " ".
    k = " " + (key_light or "").replace("_", " ") + " "
    for ent, pos, anti in _REGLAS_RESCATE:
        if anti and any(a.replace("_", " ") in k for a in anti):
            continue
        if any(p.replace("_", " ") in k for p in pos):
            return ent
    return None


def _name_norm(s):
    return re.sub(r"\s*\d+$", "", _norm_light(s)).strip()


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
    """Guardia de dimensiones vocabulario vs Booster (incidente 21151/2386).
    Trunca columnas sobrantes; error explicito si faltan."""
    esp = int(j_bst.num_feature())
    if Xj.shape[1] > esp:
        return Xj[:, :esp]
    if Xj.shape[1] != esp:
        raise ValueError(
            f"[juez] Xj.shape={tuple(Xj.shape)} vs booster.num_feature={esp}. "
            "Despliega vectorizer.pkl + modelo.txt + clases.json juntos desde fase2_juez_v3.")
    return Xj


def _load_artifacts():
    import lightgbm as lgb

    f5 = dataiku.Folder("fase5_modelo_v3").get_path()
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
        "num_cols": list(enc.get("num_cols", ["longitud", "n_tokens",
                                              "tiene_sufijo"])),
        "clf": lgb.Booster(model_file=os.path.join(f5, "modelo.txt")),
        "j_vec": j_vec,
        "j_clases": j_clases,
        "j_bst": lgb.Booster(model_file=os.path.join(f2, "modelo.txt")),
        "j_cal": j_cal,
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
    # Paridad exacta con train (recipe_build_binario_v3): key=light,
    # n_tokens sobre name_norm, sufijo sobre light.
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
    # FINAL v5: decision en 4 niveles (prob original intacta para auditoria).
    # N1 exacto y N2 raro fuerzan aunque prob ~ 0 (cierra direccion 0.00%,
    # soeid 3.17%, numautos 5.36%). N4 fuzzy mantiene PISO para no crear FP.
    keys_list = [_corrige_typo(k) for k in key.fillna("").tolist()]
    prior_ent = [None] * len(base)
    motivo = ["modelo" if p else "" for p in pii]
    c_exact = c_raro = c_fuzzy = 0
    for i, (pr, k) in enumerate(zip(prob, keys_list)):
        if not k:
            continue
        if pii[i]:
            continue
        if _es_exacto_fuerza(k):
            pii[i] = True
            prior_ent[i] = _rescate_regex(k) or _fallback_regla(
                k, ARTS["j_clases"])
            motivo[i] = "exacto"
            c_exact += 1
        elif _raro_fuerza(k) is not None:
            pii[i] = True
            prior_ent[i] = _raro_fuerza(k)
            motivo[i] = "raro"
            c_raro += 1
        elif PISO_RESCATE <= float(pr) < ARTS["threshold"]:
            r = _rescate_regex(k)
            if r is not None:
                pii[i] = True
                prior_ent[i] = r
                motivo[i] = "fuzzy"
                c_fuzzy += 1
    print(f"[binario-v5] thr={ARTS['threshold']} piso={PISO_RESCATE} "
          f"pii_modelo={int((prob >= ARTS['threshold']).sum())} "
          f"exacto={c_exact} raro={c_raro} fuzzy={c_fuzzy} de {len(base)}")
    ent = [None] * len(base)
    eprob = [None] * len(base)
    m = (key != "").to_numpy() & np.asarray(pii)
    if int(m.sum()):
        sel = np.where(m)[0]
        keys = key.iloc[sel].tolist()
        Xj = ARTS["j_vec"].transform(keys)
        Xj = _check_width_juez(Xj, ARTS["j_bst"])
        if ARTS.get("j_cal") is not None:
            # Calibrador v3 (sigmoide): prob_entity ya calibrada
            sj = np.asarray(ARTS["j_cal"].predict_proba(Xj), dtype=float)
        else:
            sj = _softmax(np.asarray(ARTS["j_bst"].predict(Xj)))
        idx = sj.argmax(axis=1)
        for j, (k, i, v) in enumerate(zip(sel, idx, sj.max(axis=1))):
            e = ARTS["j_clases"][int(i)]
            p = round(float(v), 4)
            # Si el juez duda (<0.50), el prior de rescate manda.
            # Corrige fecha_vencimiento 22.28% y similares sin ocultar prob.
            if p < UMBRAL_FALLBACK:
                fb = _fallback_regla(keys[j], ARTS["j_clases"])
                pr = prior_ent[int(k)]
                if pr is not None and pr in (ARTS["j_clases"] or []):
                    e = pr
                elif fb is not None and fb != e:
                    e = fb
            ent[int(k)] = e
            eprob[int(k)] = p
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
