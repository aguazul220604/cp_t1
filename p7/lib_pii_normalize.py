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


# ---------------------------------------------------------------- Fase 1b
# Mapping auto-propuesto 188 clusters -> ~15 entidades canonicas.
# TELEFONO fusiona tel/cel/efono/telefono (decision usuario).
CANON_EXACT = {
    "contrato": "contrato", "contract": "contrato",
    "cust": "cliente", "cliente": "cliente", "clnt": "cliente",
    "borrower": "cliente",
    "cuenta": "cuenta", "cuentabasica": "cuenta", "acct": "cuenta",
    "account": "cuenta", "nmbr": "cuenta", "im": "cuenta", "trnsfr": "cuenta",
    "addr": "direccion", "zip": "direccion", "poblacion": "direccion",
    "nacion": "direccion", "nompob": "direccion", "nomcol": "direccion",
    "merch": "direccion",
    "capital": "saldo", "sdo": "saldo", "sdodaact": "saldo", "saldo": "saldo",
    "tel": "telefono", "tel1": "telefono", "tel2": "telefono", "cel": "telefono",
    "efono": "telefono", "telefono": "telefono",
    "fnacim1": "fecha_nacimiento", "fnacim": "fecha_nacimiento",
    "dt": "fecha",
    "credito": "credito", "loan": "credito", "lmt": "credito", "imp": "credito",
    "crd": "tarjeta", "post": "tarjeta",
    "rfc": "id_persona", "nss": "id_persona", "soeid": "id_persona",
    "digitos": "id_persona",
    "nom": "nombre_persona", "name": "nombre_persona", "nm": "nombre_persona",
    "apellidomaterno": "nombre_persona", "apellidopaterno": "nombre_persona",
    "razonsocial": "nombre_persona",
    "ingresos": "ingresos",
    "cde": "otros", "line": "otros", "impcasa": "otros", "ind": "otros",
    "indicadorextranjero": "otros", "src": "otros", "tok": "otros",
    "user": "otros", "ptrmadre": "otros", "rewrite": "otros",
}

# Para raw ambiguos (num/n/nbr/v): decide por keywords del exemplar.
CANON_KEYWORDS = [
    ("tarjeta", ("tarjeta", "plastico", "card", "crd", "cheque", "cobrand")),
    ("cuenta", ("cuenta", "acct", "cta", "ctache", "ctogru")),
    ("cliente", ("cliente", "cust", "clnt")),
    ("contrato", ("contrato", "contract")),
    ("credito", ("credito", "credit", "loan", "lmt")),
    ("telefono", ("telefono", "tel", "cel", "fono", "phone")),
    ("nombre_persona", ("nombre", "nom", "beneficiario", "apellido", "razon")),
    ("id_persona", ("rfc", "nss", "curp", "soeid", "fiscal")),
    ("fecha_nacimiento", ("nacim", "fnacim")),
    ("fecha", ("fecha", "dt", "expiry", "expry")),
    ("saldo", ("saldo", "sdo", "ingreso", "capital")),
    ("direccion", ("addr", "zip", "poblacion", "municipio", "pob", "col", "nacion")),
]


def canonical_entity(raw_entity, exemplar) -> tuple:
    """Devuelve (canon, metodo). Strip digitos: tel1->tel."""
    raw = (raw_entity or "").strip().lower()
    raw = TRAILING_NUM.sub("", raw).strip() or raw
    if raw in CANON_EXACT:
        return CANON_EXACT[raw], "exact"
    exe = (exemplar or "").lower()
    blob = f"{raw} {exe}"
    for canon, kws in CANON_KEYWORDS:
        if any(k in blob for k in kws):
            return canon, "exemplar"
    return ("numero" if raw in ("num", "n", "nbr", "v") and "num" in blob
            else "otros"), "fallback"


# ---------------------------------------------------------------- Fase 2
MIN_EJEMPLOS_CLASE = 3


def preparar_juez(df: pd.DataFrame, feat_col: str = "light",
                  target_col: str = "entity_canon") -> tuple:
    """Filtra canon no nula; fusiona clases con <MIN_EJEMPLOS_CLASE a 'otros'.
    Devuelve (df_listo, fusionadas: dict)."""
    base = df[df[target_col].notna()].copy()
    counts = base[target_col].value_counts()
    debiles = [c for c, n in counts.items() if n < MIN_EJEMPLOS_CLASE]
    base[target_col] = base[target_col].apply(
        lambda c: "otros" if c in debiles else c)
    return base, {c: int(counts[c]) for c in debiles}


# ---------------------------------------------------------------- Fase 7/8
# Inferencia produccion/piloto. Requiere artefactos de fase5_modelo y fase2_juez.
# Sin dependencias fuera de pandas/sklearn/lightgbm/scipy base.
def cargar_artefactos(fase5_dir: str, fase2_dir: str) -> dict:
    import json
    import os
    import pickle

    import lightgbm as lgb

    with open(os.path.join(fase5_dir, "vec_name.pkl"), "rb") as f:
        vec_name = pickle.load(f)
    with open(os.path.join(fase5_dir, "encoders.json"), encoding="utf-8") as f:
        enc = json.load(f)
    with open(os.path.join(fase2_dir, "vectorizer.pkl"), "rb") as f:
        j_vec = pickle.load(f)
    with open(os.path.join(fase2_dir, "clases.json"), encoding="utf-8") as f:
        j_clases = json.load(f)
    return {"vec_name": vec_name, "te_map": enc["te_map"],
            "te_global": float(enc["te_global"]),
            "top_types": enc["top_types"],
            "threshold": float(enc["threshold"]),
            "variante": enc.get("variante", "A"),
            "clf": lgb.Booster(model_file=os.path.join(fase5_dir, "modelo.txt")),
            "j_vec": j_vec, "j_clases": j_clases,
            "j_bst": lgb.Booster(model_file=os.path.join(fase2_dir, "modelo.txt"))}


def featurizar_inferencia(df: pd.DataFrame, arts: dict):
    import numpy as np
    from scipy.sparse import csr_matrix, hstack

    base = df.copy()
    base["key"] = base["name"].map(join_key)
    base["longitud"] = base["name"].fillna("").astype(str).str.len()
    if "description" in base.columns:
        base["has_description"] = base["description"].notna() & (
            base["description"].astype(str).str.strip() != "")
    else:
        base["has_description"] = False
    if "type" not in base.columns:
        base["type"] = "UNKNOWN"
    if "dataset" not in base.columns:
        base["dataset"] = "piloto"
    Xn = arts["vec_name"].transform(base["key"].fillna("").tolist())
    te = base["dataset"].map(arts["te_map"]).fillna(arts["te_global"]).values
    top = arts["top_types"]
    s = base["type"].fillna("").where(base["type"].isin(top), "OTROS")
    import pandas as _pd
    typ = _pd.get_dummies(s, prefix="typ").reindex(
        columns=["typ_" + t for t in top] + ["typ_OTROS"],
        fill_value=0).astype(np.int8).values
    num = np.vstack([base["longitud"].values,
                     base["has_description"].astype(int).values, te]).T
    X = hstack([Xn, csr_matrix(num), csr_matrix(typ)]).tocsr()
    return base, X


def _softmax(scores: np.ndarray) -> np.ndarray:
    import numpy as np

    if scores.ndim == 1:
        scores = np.vstack([1 - scores, scores]).T
    if not np.allclose(scores.sum(axis=1), 1.0, atol=1e-3):
        e = np.exp(scores - scores.max(axis=1, keepdims=True))
        scores = e / e.sum(axis=1, keepdims=True)
    return scores


def predecir(df: pd.DataFrame, arts: dict) -> pd.DataFrame:
    import numpy as np

    base, X = featurizar_inferencia(df, arts)
    prob = np.asarray(arts["clf"].predict(X)).ravel()
    base["prob_pii"] = np.round(prob, 4)
    base["pii"] = prob >= arts["threshold"]
    base["entity"] = None
    base["prob_entity"] = np.nan
    mask = base["key"] != ""
    pmask = mask & base["pii"]
    if int(pmask.sum()):
        Xj = arts["j_vec"].transform(base.loc[pmask, "key"].tolist())
        sj = _softmax(np.asarray(arts["j_bst"].predict(Xj)))
        idx = sj.argmax(axis=1)
        base.loc[pmask, "entity"] = [arts["j_clases"][i] for i in idx]
        base.loc[pmask, "prob_entity"] = np.round(sj.max(axis=1), 4)
    return base


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
