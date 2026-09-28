# Pegar en Dataiku: Library Editor > pii_lib > normalize.py
# Proyecto: PII_LGBM — Fases 0/1/3a. Sin dependencias fuera de pandas/sklearn base.
import re
import unicodedata

import numpy as np
import pandas as pd
from sklearn.cluster import AffinityPropagation, AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

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


def normalize_light_split(s) -> str:
    """Light + split raices, SIN strip de digitos (para nombrar clusters Fase 1)."""
    return _split_roots(normalize_light(s))


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


def join_key(s) -> str:
    """Clave robusta de join: light (lower, sin acentos, trim). '' si nulo/vacio."""
    return normalize_light(s)


def dedup_catalog(df: pd.DataFrame, col: str = "name",
                  pii_col: str = "pii") -> pd.DataFrame:
    tmp = df[[col, pii_col]].copy()
    tmp["_is_pii"] = parse_pii(tmp[pii_col])
    tmp["_light"] = tmp[col].map(normalize_light)
    tmp["_aggr"] = tmp[col].map(normalize_aggr)
    tmp["_key"] = tmp[col].map(join_key)
    g = tmp.groupby(col, as_index=False).agg(
        n_rows=(col, "size"),
        n_true=("_is_pii", "sum"),
        light=("_light", "first"),
        aggr=("_aggr", "first"),
        key=("_key", "first"),
    )
    g["pii_any"] = g["n_true"] > 0
    g["pii_majority"] = g["n_true"] * 2 >= g["n_rows"]
    return g


# ---------------------------------------------------------------- Fase 1
def build_char_tfidf(texts: list) -> tuple:
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
    X = vec.fit_transform([t or "" for t in texts])
    return vec, X


def cluster_affinity_sweep(S: np.ndarray, random_state: int = 0) -> dict:
    """Barre preference en p50/p70/p90. Devuelve {pref: labels}."""
    prefs = [float(np.percentile(S, p)) for p in (50, 70, 90)]
    out = {}
    for pref in prefs:
        ap = AffinityPropagation(affinity="precomputed",
                                 preference=pref, random_state=random_state)
        out[pref] = ap.fit_predict(S)
    return out


def cluster_fallback(X, n_below: int = 3, n_above: int = 50,
                     labels=None) -> np.ndarray:
    """Si AP da <n_below o >n_above clusters (o vacio), usa Aglomerativo."""
    if labels is not None:
        k = len(set(labels)) - (1 if -1 in labels else 0)
        if n_below <= k <= n_above:
            return np.asarray(labels)
    agg = AgglomerativeClustering(
        n_clusters=None, distance_threshold=0.5,
        metric="cosine", linkage="average")
    return agg.fit_predict(X.toarray() if hasattr(X, "toarray") else X)


def name_clusters(light_texts: list, labels) -> dict:
    """TF-IDF palabra-bigrama por cluster; termino top = Entity."""
    df = pd.DataFrame({"t": light_texts, "c": list(labels)})
    names = {}
    for c, grp in df.groupby("c"):
        docs = grp["t"].tolist()
        if len(docs) == 1:
            tok = (docs[0] or "").split()
            names[c] = tok[0] if tok else f"cluster_{c}"
            continue
        v = TfidfVectorizer(analyzer="word", ngram_range=(1, 2))
        X = v.fit_transform(docs)
        top = v.get_feature_names_out()[int(X.sum(axis=0).argmax())]
        names[c] = top.split()[0]
    return names


# ---------------------------------------------------------------- Fase 3a
THRESH_FUERTE = 90.0
THRESH_PARCIAL = 50.0
W_SIN_EVIDENCIA = 0.3


def assign_pii_final(similarity: float, vecino_pii: bool, pii_orig: bool):
    if similarity >= THRESH_FUERTE:
        return bool(vecino_pii), "validado_21k", 1.0
    if similarity >= THRESH_PARCIAL:
        return bool(vecino_pii), "evidencia_parcial", round(float(similarity) / 100, 4)
    return bool(pii_orig), "sin_evidencia_mantenido", W_SIN_EVIDENCIA
