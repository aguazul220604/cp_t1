# Pegar en Dataiku: Library Editor > pii_lib > normalize.py
# Proyecto: PII_LGBM — Fase 0. Sin dependencias fuera de pandas/sklearn base.
import re
import unicodedata

import pandas as pd

ROOTS = ["cliente", "telefono", "poblacion", "destino", "linea",
         "nombre", "fecha", "nacim", "banco", "capt",
         "situacion", "num", "tel", "cta", "fec", "dir"]

TRAILING_NUM = re.compile(r"\s*\d+$")


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def normalize_light(s) -> str:
    """Minusculas, sin acentos, trim, colapsa espacios. CONSERVA digitos."""
    if pd.isna(s):
        return ""
    s = _strip_accents(str(s).lower())
    return re.sub(r"\s+", " ", s).strip()


def _split_roots(s: str) -> str:
    for root in sorted(ROOTS, key=len, reverse=True):
        s = re.sub(rf"(?<=[a-z])({root})(?=[a-z])", r" \1 ", s)
        s = re.sub(rf"(?<=[a-z])({root})$", r" \1", s)
        s = re.sub(rf"^({root})(?=[a-z])", r"\1 ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_aggr(s) -> str:
    """Light + strip sufijo numerico + split raices pegadas."""
    base = TRAILING_NUM.sub("", normalize_light(s)).strip()
    return _split_roots(base)


def parse_pii(col: pd.Series) -> pd.Series:
    """Acepta boolean nativo Dataiku, 'TRUE'/'FALSE', 1/0."""
    if col.dtype == object:
        return col.astype(str).str.upper().isin(["TRUE", "1", "T", "SI"])
    if col.dtype == bool:
        return col
    return col.astype(bool)


def bucket(score: float) -> str:
    if score >= 90:
        return "fuerte(>=90)"
    if score >= 50:
        return "parcial(50-90)"
    return "nula(<50)"


def dedup_catalog(df: pd.DataFrame, col: str = "name",
                  pii_col: str = "pii") -> pd.DataFrame:
    tmp = df[[col, pii_col]].copy()
    tmp["_is_pii"] = parse_pii(tmp[pii_col])
    tmp["_light"] = tmp[col].map(normalize_light)
    tmp["_aggr"] = tmp[col].map(normalize_aggr)
    g = tmp.groupby(col, as_index=False).agg(
        n_rows=(col, "size"),
        n_true=("_is_pii", "sum"),
        light=("_light", "first"),
        aggr=("_aggr", "first"),
    )
    g["pii_any"] = g["n_true"] > 0
    g["pii_majority"] = g["n_true"] * 2 >= g["n_rows"]
    return g
