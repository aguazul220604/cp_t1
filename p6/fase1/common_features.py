"""Features comunes Fase 1 - PII solo con `name`.
Reutilizable en prepare / train / score para evitar train-serve skew.
"""
import re
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

# Patrones de dominio (banderas regex). No son labels, solo señales.
PII_PATTERNS = {
    "kw_tel": r"\b(?:tel|telefono|tel[eé]fono|phone|cel|movil|m[oó]vil)\b",
    "kw_email": r"\b(?:email|e-mail|mail|correo)\b",
    "kw_rfc": r"\brfc\b",
    "kw_curp": r"\bcurp\b",
    "kw_nombre": r"\b(?:nom|nombre|nombres|apellido|apellidos)\b",
    "kw_dir": r"\b(?:dir|direccion|direcci[oó]n|calle|colonia|cp|c\.p\.|domicilio)\b",
    "kw_nac": r"\b(?:nac|nacimiento|curp|ine|ife|pasaporte)\b",
    "kw_cta": r"\b(?:cta|cuenta|clabe|tarjeta|credito|cr[eé]dito)\b",
    "kw_id": r"\b(?:id|folio|clave|rfc|curp|ine)\b",
}

# Sufijos/calificadores que cambian el sentido (tel casa1 PII vs tel casa ict1 no PII)
SUFFIX_PATTERNS = {
    "suf_num": r"\d+\s*$",
    "suf_ict": r"\bict\d*\b",
    "suf_test": r"\b(?:test|testigo|dummy|ejemplo|prueba)\b",
    "suf_flag": r"\b(?:flag|ind|indicador|marca|check)\b",
    "suf_desc": r"\b(?:desc|descripcion|descripci[oó]n|obs|observ)\b",
}

SEED = 42


def clean_name(s: str) -> str:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    s = str(s).lower().strip()
    s = re.sub(r"[_\-/|;:.]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def base_entity(s: str) -> str:
    """Entidad base aproximada: quita sufijo numérico final e ict/test/flag."""
    s = clean_name(s)
    s = re.sub(r"\s+ict\d*\s*$", "", s)
    s = re.sub(r"\s+(test|dummy|prueba|flag|ind|marca)\d*\s*$", "", s)
    s = re.sub(r"\s+\d+\s*$", "", s).strip()
    return s


class NameNumericFeatures(BaseEstimator, TransformerMixin):
    """Features numéricas + regex sobre `name_clean`. Devuelve DataFrame."""

    def __init__(self):
        self.entity_top_ = []

    def fit(self, X, y=None):
        # Guarda top entidades base de la clase PII para fuzzy posterior (solo train)
        try:
            s = pd.Series(X["name_clean"] if isinstance(X, pd.DataFrame) else X)
            if y is not None:
                s_pii = s[pd.Series(y).values == 1].map(base_entity)
                self.entity_top_ = s_pii.value_counts().head(200).index.tolist()
        except Exception:
            self.entity_top_ = []
        return self

    def transform(self, X):
        if isinstance(X, pd.DataFrame):
            s = X["name_clean"].astype(str)
        else:
            s = pd.Series(list(X)).astype(str)
        out = pd.DataFrame(index=s.index)
        out["longitud"] = s.str.len()
        out["n_tokens"] = s.str.split().str.len().fillna(0)
        out["tiene_digito"] = s.str.contains(r"\d").astype(int)
        out["n_digitos"] = s.str.count(r"\d")
        for k, pat in {**PII_PATTERNS, **SUFFIX_PATTERNS}.items():
            out[f"rgx_{k}"] = s.str.contains(pat, regex=True).astype(int)
        return out


def build_tfidf():
    return TfidfVectorizer(
        analyzer="char_wb", ngram_range=(3, 5), min_df=5, max_features=20000
    )


def fuzzy_max_score(query: str, choices, scorer=None) -> float:
    """Distancia fuzzy vs diccionario top-entidades. Lazy import para no exigir rapidfuzz en Dataiku si falta."""
    if not query or not choices:
        return 0.0
    try:
        from rapidfuzz import fuzz
        sc = scorer or fuzz.WRatio
        best = 0.0
        q = base_entity(query)
        for c in choices:
            v = sc(q, c)
            if v > best:
                best = float(v)
                if best >= 99:
                    break
        return best
    except ImportError:
        # Fallback barato: overlap de tokens
        q = set(base_entity(query).split())
        best = 0.0
        for c in choices:
            t = set(str(c).split())
            if not q or not t:
                continue
            v = 100.0 * len(q & t) / max(len(q | t), 1)
            best = max(best, v)
        return float(best)


def add_fuzzy_feature(df: pd.DataFrame, entity_top: list) -> pd.DataFrame:
    df = df.copy()
    df["fuzzy_entity_score"] = df["name_clean"].map(
        lambda x: fuzzy_max_score(x, entity_top)
    )
    return df
