# Pegar en Dataiku: Library Editor > pii_lib > juez_v2.py
# Helpers del Juez supervisado 23 clases. Solo usa `name`.
# Sin dependencias fuera de pandas/sklearn/lightgbm.
import re
import unicodedata

import pandas as pd

# Reglas deterministas SOLO para ultra-raras / desempates.
# Se aplican DESPUES del modelo si prob < umbral, nunca solas.
REGLAS_FALLBACK = [
    ("curp", ("curp",)),
    ("rfc", ("rfc",)),
    ("nss", ("nss", "num_seguro_social", "seguro_social")),
    ("correo", ("correo", "email", "mail", "e_mail")),
    ("sexo", ("sexo", "genero")),
    ("fecha_vencimiento", ("venc", "expira", "expiry", "vigencia")),
    ("fecha_nacimiento", ("nacim", "fnacim", "birth")),
    ("telefono", ("tel", "cel", "fono", "phone")),
    ("tarjeta", ("tarjeta", "plastico", "card", "crd")),
    ("cuenta", ("cuenta", "acct", "cta", "ctogru")),
    ("cliente", ("cliente", "cust", "clnt")),
]


def light(s) -> str:
    if pd.isna(s):
        return ""
    s = "".join(c for c in unicodedata.normalize("NFD", str(s).lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def name_norm(s) -> str:
    return re.sub(r"\s*\d+$", "", light(s)).strip()


def group_id(s) -> str:
    return re.sub(r"[\s\-_]", "", name_norm(s))


def preparar_juez_supervisado(df, target_col="entity", min_ejemplos=2):
    """Fuente de verdad = tu columna manual. NO fusiona a 'otros'.
    Solo filtra clases con < min_ejemplos (defecto 2 = minimo para CV).
    Devuelve (base, info). `otro_pii` se conserva siempre aunque sea rara."""
    base = df[df[target_col].notna()].copy()
    base[target_col] = base[target_col].astype(str).str.strip().str.lower()
    base = base[base[target_col] != ""].copy()
    base["light"] = base["name"].map(light)
    base["name_norm"] = base["name"].map(name_norm)
    base["group_id"] = base["name"].map(group_id)
    counts = base[target_col].value_counts()
    # otro_pii es cajon intencional: nunca se elimina
    eliminadas = {c: int(n) for c, n in counts.items()
                  if n < min_ejemplos and c != "otro_pii"}
    base = base[~base[target_col].isin(eliminadas)].reset_index(drop=True)
    info = {"clases": sorted(base[target_col].unique().tolist()),
            "n": len(base), "eliminadas": eliminadas,
            "soporte": {c: int(n) for c, n in counts.items()}}
    return base, info


def aumentar_raras(textos, entity, n_objetivo=15, seed=0):
    """Duplica con variantes reales de escritura para llegar a n_objetivo.
    Solo altera espacios/guiones y sufijo numerico: no inventa vocabulario."""
    import numpy as np
    rng = np.random.RandomState(seed)
    out_t, out_y = list(textos), list(entity)
    s = pd.Series(entity)
    for cls, n in s.value_counts().items():
        need = int(n_objetivo - n)
        if need <= 0:
            continue
        pool = [t for t, y in zip(textos, entity) if y == cls]
        for _ in range(need):
            t = pool[rng.randint(len(pool))]
            v = rng.choice(["nospace", "suf1", "suf2", "undersc", "same"])
            if v == "nospace":
                t2 = re.sub(r"[\s\-_]", "", t)
            elif v == "undersc":
                t2 = re.sub(r"\s+", "_", t)
            elif v == "suf1":
                t2 = f"{t} {rng.randint(1, 9)}"
            elif v == "suf2":
                t2 = f"{t}{rng.randint(1, 99)}"
            else:
                t2 = t
            out_t.append(t2)
            out_y.append(cls)
    return out_t, out_y


def fallback_regla(key_light):
    """Devuelve entidad por keyword o None. key_light ya normalizado."""
    k = f" {key_light} ".replace("_", " ")
    for ent, kws in REGLAS_FALLBACK:
        if any(kw in k for kw in kws):
            return ent
    return None


def aplicar_fallback(keys, entidades, probas, umbral=0.5):
    """Si prob < umbral y la regla matchea, corrige a la regla.
    Nunca degrada una prediccion confiable."""
    out_e, out_p, tocadas = [], [], 0
    for k, e, p in zip(keys, entidades, probas):
        fb = fallback_regla(k or "")
        if p < umbral and fb is not None and fb != e:
            out_e.append(fb)
            out_p.append(round(float(p), 4))
            tocadas += 1
        else:
            out_e.append(e)
            out_p.append(round(float(p), 4))
    return out_e, out_p, tocadas
