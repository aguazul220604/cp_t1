# Lib Fase 2a — normalización name -> name_norm (v3 MVP v2).
# Pegar en Dataiku: Library Editor > pii_lib_v3 > normalize_v3.py
# Regla spec Fase 2a: minusculas, separar camelCase y guiones bajos,
# eliminar sufijos numericos finales (tel casa1 -> tel casa).
import re
import unicodedata

TRAILING_NUM = re.compile(r"[\s_\-]*\d+\s*$")
TRAILING_LETTER = None  # no se usa: A/B se conservan en name crudo, se borran solo via normalizacion si van con numero

CALIFICADORES_NO_PII = [
    r"\bict\d*\b", r"\bautenticado\d*\b", r"\borigen\b", r"\bsuborigen\b",
    r"\bservicio\b", r"\bseguridad\b",
]


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def split_camel(s: str) -> str:
    # separa camelCase: telCasa -> tel Casa ; NumCliente -> Num Cliente
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    return s


def normalize_name(s) -> str:
    """name -> name_norm segun spec Fase 2a."""
    if s is None:
        return ""
    try:
        import pandas as pd
        if pd.isna(s):
            return ""
    except Exception:
        pass
    s = str(s)
    s = split_camel(s)
    s = s.lower()
    s = _strip_accents(s)
    # separadores -> espacio (incluye _ - / . | ; : )
    s = re.sub(r"[_\-/|;:.]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # eliminar sufijo numerico final: "tel casa 1" / "tel casa1" -> "tel casa"
    # primero colapsa letra+digito pegado: casa1 -> casa 1
    s = re.sub(r"(?<=[a-z])(\d+)$", r" \1", s)
    s = re.sub(r"(?<=[a-z])(\d+)(?=\s)", r" \1 ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = TRAILING_NUM.sub("", s).strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_pii(col):
    """Acepta boolean Dataiku, 'TRUE'/'FALSE', 1/0."""
    import pandas as pd
    if col.dtype == bool:
        return col.fillna(False)
    s = col.astype(str).str.strip().str.upper()
    return s.isin(["TRUE", "1", "T", "SI", "YES"])


# 23 entidades conservadas (doc v2 §1). Orden no importa aqui.
ENTIDADES_23 = [
    "cuenta", "cliente", "saldo", "contrato", "credito", "telefono",
    "direccion", "tarjeta", "nombre", "fecha_nacimiento", "rfc", "nomina",
    "otro_pii", "fecha_vencimiento", "credenciales_id", "apellido", "sexo",
    "datos_demograficos", "documento_legal", "correo", "curp", "nss",
    "bienes_patrimonio",
]

TIER_1_SIN_SINTETICOS = {
    "cuenta", "cliente", "saldo", "contrato", "credito",
    "telefono", "direccion", "tarjeta",
}
TIER_2_REFUERZO = {"nombre", "fecha_nacimiento", "rfc", "nomina"}
TIER_3_COMPLETO = {
    "otro_pii", "fecha_vencimiento", "credenciales_id", "apellido", "sexo",
    "datos_demograficos", "documento_legal", "correo", "curp", "nss",
    "bienes_patrimonio",
}
# Entidades regexables: 0 typos permitidos aqui (spec 2c).
ENTIDADES_CERO_TYPOS = {"curp", "rfc", "nss", "correo", "sexo", "fecha_nacimiento", "fecha_vencimiento"}
