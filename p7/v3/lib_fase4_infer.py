# Lib Fase 4 — inferencia A/B + override regex (v3 MVP v2).
# Pegar en Dataiku: Library Editor > pii_lib_v3 > fase4_infer.py
# Umbral fijo UMBRAL_ENTITY=0.5 (recomendado arranque; ver decision Fase 3).
# regex portado 1:1 de regex.txt (orden especifico->generico).
import re

UMBRAL_ENTITY = 0.5

# (entidad, [patrones]) en el mismo orden que regex.txt.
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


def regex_all_matches(name: str) -> list:
    """Todas las entidades cuyos patrones matchean (sobre name crudo, lower)."""
    s = str(name or "")
    out = []
    for ent, pats in _COMPILED:
        if any(p.search(s) for p in pats):
            out.append(ent)
    return out


def regex_first_match(name: str) -> str:
    """Equivalente al if-anidado de regex.txt: primer match o 'otro_pii'."""
    m = regex_all_matches(name)
    return m[0] if m else "otro_pii"


def aplicar_override(entity_ml, prob_entity, name, umbral=UMBRAL_ENTITY):
    """Si prob<umbral y regex da UN unico match -> override. Si ambiguo (0 o 2+), conserva ML."""
    matches = regex_all_matches(name)
    if prob_entity is not None and float(prob_entity) < float(umbral) and len(matches) == 1:
        return matches[0], True, matches[0]
    # Sin override: reporta first-match solo como debug (equivale a regex.txt)
    dbg = matches[0] if len(matches) == 1 else (None if not matches else "ambiguo")
    return entity_ml, False, dbg


def predecir_df(df_names, vecs_a, clf_a, platt_a, umbral_a, vecs_b, clf_b, clases_b,
                umbral_entity=UMBRAL_ENTITY):
    """df_names: DataFrame con columna 'name'. Devuelve DataFrame formato §4 + debug."""
    import numpy as np
    import pandas as pd
    try:
        from pii_lib_v3.fase3_common import apply_platt as _ap, apply_vectorizers as _av
        from pii_lib_v3.normalize_v3 import normalize_name as _nn
        _apply_platt, _apply_vec, _norm = _ap, _av, _nn
    except ImportError:
        from lib_fase3_common import apply_platt, apply_vectorizers
        from lib_fase2_normalize import normalize_name
        _apply_platt, _apply_vec, _norm = apply_platt, apply_vectorizers, normalize_name

    names = df_names["name"].fillna("").astype(str)
    norms = names.map(_norm)
    Xa = _apply_vec(vecs_a, norms.tolist())
    raw = np.asarray(clf_a.predict_proba(Xa)[:, 1]).ravel()
    try:
        prob_a = _apply_platt(platt_a, raw)
    except Exception:
        prob_a = raw
    pii = prob_a >= float(umbral_a)

    entity = pd.Series([None] * len(names), dtype=object)
    prob_e = pd.Series([np.nan] * len(names), dtype=float)
    idx = np.where(pii)[0]
    if len(idx):
        Xb = _apply_vec(vecs_b, norms.iloc[idx].tolist())
        if hasattr(clf_b, "predict_proba"):
            sb = np.asarray(clf_b.predict_proba(Xb))
            # alinear columnas del clf con clases_b (LGBM/LogReg guardan order en classes_)
            order = list(getattr(clf_b, "classes_", clases_b))
            bi = sb.argmax(axis=1)
            entity.iloc[idx] = [order[i] for i in bi]
            prob_e.iloc[idx] = sb.max(axis=1)
        else:
            entity.iloc[idx] = clf_b.predict(Xb)
            prob_e.iloc[idx] = np.nan

    out = pd.DataFrame({
        "columna": names.values,
        "name_norm": norms.values,
        "pii": [bool(v) for v in pii],
        "prob_pii": np.round(prob_a, 4),
        "entity": [e if p else None for e, p in zip(entity.values, pii)],
        "prob_entity": [round(float(v), 4) if p and v == v else np.nan
                        for v, p in zip(prob_e.values, pii)],
    })
    # Override fila a fila (solo donde pii=TRUE)
    ov_ent, ov_flag, ov_dbg = [], [], []
    for e, pe, nm, p in zip(out["entity"], out["prob_entity"], names, pii):
        if not p:
            ov_ent.append(None)
            ov_flag.append(False)
            ov_dbg.append(None)
        else:
            pe_val = None if (pe != pe) else float(pe)
            ne, flag, dbg = aplicar_override(e, pe_val if pe_val is not None else 1.0,
                                             nm, umbral_entity)
            ov_ent.append(ne)
            ov_flag.append(flag)
            ov_dbg.append(dbg)
    out["entity_final"] = [ne if f else e for ne, f, e in
                           zip(ov_ent, ov_flag, out["entity"])]
    out["override_aplicado"] = ov_flag
    out["regex_match"] = ov_dbg
    return out
