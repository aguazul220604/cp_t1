"""Taxonomía de entidades PII + resolver determinístico.
Responde a: `numtel` y `tel casa1` son PII ambos pero distinta superficie -> misma entidad TELEFONO.
Y `tel casa1` (PII) vs `tel casa ict1` (no PII): misma entidad, distinto PII -> entidad y PII son salidas independientes.

Ningún dataset trae label de entidad, por eso NO es un clasificador supervisado:
es diccionario regex ordenado (específico->genérico) sobre nombre expandido + fuzzy fallback.
Salida final por columna: pii (0/1 del LightGBM), prob_pii, entity, prob_entity.
"""
import re

# Expansión de abreviaturas típicas Banamex (ver screenshot 267k: sdo, fnacim, num, cte, dir, cve...)
ABBREV = {
    r"\bnum\b": "numero",
    r"\bnumtel\b": "numero telefono",
    r"\bnumcliente\b": "numero cliente",
    r"\btel\b": "telefono",
    r"\btels\b": "telefono",
    r"\bsdo\b": "saldo",
    r"\bintvig\b": "interes vigente",
    r"\bfnacim\b": "fecha nacimiento",
    r"\bfec\b": "fecha",
    r"\bultla\b": "ultima",
    r"\bult\b": "ultimo",
    r"\bantiguedad\b": "antiguedad",
    r"\bdir\b": "direccion",
    r"\bcte\b": "cliente",
    r"\bcve\b": "clave",
    r"\bnom\b": "nombre",
    r"\bdigverificador\b": "digito verificador",
    r"\bsoeid\b": "employee id",
    r"\bcsi\b": "csi",
    r"\bsitcte\b": "situacion cliente",
    r"\bsitcta\b": "situacion cuenta",
    r"\bhor\b": "hora",
    r"\bfinact\b": "fin actividad",
    r"\bpag\b": "pago",
    r"\biva\b": "iva",
    r"\bnumpord\b": "numero producto",
    r"\bnumprod\b": "numero producto",
    r"\bd81\b": "d81",
    r"\bpromcap\b": "promedio captacion",
    r"\binst\b": "instrumento",
}

# Orden importa: lo específico primero. Regex sobre texto ya expandido y en minúsculas.
ENTITY_PATTERNS = [
    ("TELEFONO", [r"telefono", r"numero telefono", r"\btel casa\b", r"numtel", r"\bcel\b", r"movil", r"phone"]),
    ("EMAIL", [r"email", r"e mail", r"correo"]),
    ("RFC", [r"\brfc\b"]),
    ("CURP", [r"\bcurp\b"]),
    ("CUENTA", [r"numero cliente", r"numcliente", r"numero cuenta", r"\bcuenta\b", r"\bclabe\b", r"lineacapt", r"instrumento", r"\binst\b"]),
    ("TARJETA", [r"tarjeta", r"\btdc\b", r"digito verificador", r"digverificador"]),
    ("NOMBRE", [r"nombre", r"apellido", r"\bnom\b"]),
    ("DIRECCION", [r"direccion", r"poblacion", r"colonia", r"calle", r"domicilio", r"banco destino"]),
    ("FECHA_NACIMIENTO", [r"fecha nacimiento", r"fnacim", r"nacimiento"]),
    ("IDENTIFICADOR", [r"employee id", r"soeid", r"folio", r"clave", r"\bcve\b", r"situacion"]),
]

# Sufijos que NO cambian entidad pero sí pueden cambiar PII (metadata, no dato real)
NON_PII_QUALIFIERS = [r"\bict\d*\b", r"autenticado", r"antiguedad", r"origen", r"suborigen",
                      r"servicio", r"seguridad", r"suborg", r"fec ult", r"hr ult", r"fec alta"]


def expand(name_clean: str) -> str:
    s = f" {name_clean} "
    for pat, rep in ABBREV.items():
        s = re.sub(pat, rep, s)
    return re.sub(r"\s+", " ", s).strip()


def predict_entity(name: str):
    """Devuelve (entity, prob_entity, metodo). prob_entity = confianza del mapeo, NO de PII."""
    from common_features import clean_name
    nc = clean_name(name)
    if not nc:
        return "DESCONOCIDO", 0.0, "vacio"
    exp = expand(nc)
    for ent, pats in ENTITY_PATTERNS:
        for p in pats:
            if re.search(p, exp):
                # 1.0 si match en expandido, 0.9 si solo en crudo (abreviatura sin expandir)
                return ent, 1.0, "regex"
    # Fallback fuzzy contra ejemplos canónicos
    cands = {"TELEFONO": "telefono casa", "CUENTA": "numero cliente",
             "NOMBRE": "nombre cliente", "DIRECCION": "direccion poblacion",
             "FECHA_NACIMIENTO": "fecha nacimiento", "EMAIL": "email"}
    try:
        from rapidfuzz import fuzz
        best, be = 0, "DESCONOCIDO"
        for ent, ex in cands.items():
            v = fuzz.WRatio(exp, ex)
            if v > best:
                best, be = v, ent
        if best >= 80:
            return be, round(best / 100, 2), "fuzzy"
    except ImportError:
        pass
    return "DESCONOCIDO", 0.0, "fallback"


def is_qualified_metadata(name: str) -> bool:
    from common_features import clean_name
    nc = clean_name(name)
    return any(re.search(p, nc) for p in NON_PII_QUALIFIERS)
