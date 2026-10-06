# Dataiku Python recipe: fase2c_aumento_sintetico
# In (Flow):  dataset_validated_norm (name, name_norm, entity, pii)
#             variantes_lexicas_267k (evidencia 2b — define operadores permitidos)
# Out (Flow): aug_train_only (name, entity, is_synthetic=1, parent_norm)
#             SOLO-TRAIN: jamas mezclar en CSV canonico ni usar en val/test/calibracion/reporte.
#
# Reglas spec §2c: cap parejo 30 distintos por entidad (need = 30 - n_distinto),
# Tier1 sin sinteticos, Tier2 refuerzo, Tier3 completo,
# operadores preservan entidad sin cruzar clases, dedup por name_norm,
# hijo al mismo fold que parent_norm, 0 typos en curp/rfc/nss/correo/sexo/fecha_*.
#
# Local: python recipe_fase2c_aumento_sintetico.py --input norm.csv --output aug.csv
import argparse
import random
import re

import pandas as pd

try:
    import dataiku
    HAS_DATAIKU = True
except ImportError:
    HAS_DATAIKU = False

try:
    # DSS Library Editor: pii_lib_v3 > normalize_v3.py
    from pii_lib_v3.normalize_v3 import (
        ENTIDADES_CERO_TYPOS, TIER_1_SIN_SINTETICOS, normalize_name,
    )
except ImportError:
    # Local
    from lib_fase2_normalize import (
        ENTIDADES_CERO_TYPOS, TIER_1_SIN_SINTETICOS, normalize_name,
    )

IN_NORM = "dataset_validated_norm"
# NOTA: variantes_lexicas_267k NO se lee como input en esta recipe.
# ABBREV_MAP ya esta restringido al diccionario permitido de Fase 2b.
# Si quieres validarlo contra el dataset, enlaza el dataset como 2do input
# y filtra; por defecto no se exige para no bloquear el build.
IN_VAR_OPTIONAL = "variantes_lexicas_267k"
OUT_AUG = "aug_train_only"
CAP = 30
SEED = 42

# Mapa abreviatura<->expandido SOLO si esta en diccionario Fase 2b.
# Clave: token normalizado -> lista de formas alternas observadas.
ABBREV_MAP = {
    "correo": ["mail", "email", "e-mail"],
    "mail": ["correo", "email"],
    "email": ["correo", "mail"],
    "telefono": ["tel", "cel", "phone", "ph"],
    "tel": ["telefono", "cel", "phone"],
    "cel": ["tel", "telefono"],
    "cuenta": ["acct", "cta", "acnt"],
    "acct": ["cuenta", "cta"],
    "cta": ["cuenta", "acct"],
    "tarjeta": ["card", "crd", "plastico"],
    "card": ["tarjeta", "crd"],
    "crd": ["tarjeta", "card"],
    "cliente": ["clnt", "cust"],
    "clnt": ["cliente", "cust"],
    "cust": ["cliente", "clnt"],
    "rfc": ["id_fiscal", "idfiscal"],
    "sexo": ["gndr"],
    "direccion": ["addr", "dir"],
    "addr": ["direccion"],
    "calle": ["clle"],
    "nomina": ["numemp", "numnom"],
    "saldo": ["sdo", "balance"],
    "sdo": ["saldo"],
    "contrato": ["contract", "cto"],
    "contract": ["contrato"],
}
CALIFICADORES = ["titular", "cliente", "beneficiario"]
SUFIJOS_BAJA = ["1", "2", "A", "B"]


def op_separadores_casing(base: str, rng: random.Random) -> str:
    toks = base.split()
    if not toks:
        return base
    sep = rng.choice([" ", "_", "-", ".", ""])
    s = sep.join(toks)
    # casing: 80% lower en regexables se maneja fuera; aqui mezcla observada
    r = rng.random()
    if r < 0.5:
        return s.lower()
    if r < 0.75:
        return s.upper()
    return " ".join(t.capitalize() for t in toks) if sep == " " else s


def op_abbrev(base: str, rng: random.Random):
    toks = base.split()
    for i, t in enumerate(toks):
        if t in ABBREV_MAP and rng.random() < 0.5:
            toks[i] = rng.choice(ABBREV_MAP[t])
            return " ".join(toks), True
    return base, False


def op_calificador(base: str, rng: random.Random) -> str:
    c = rng.choice(CALIFICADORES)
    return f"{c} {base}" if rng.random() < 0.5 else f"{base} {c}"


def op_sufijo(base: str, rng: random.Random) -> str:
    return f"{base} {rng.choice(SUFIJOS_BAJA)}"


def generar_para_padre(padre_norm: str, entity: str, rng: random.Random) -> str:
    """Un hijo sintético preservando entidad. Sin typos nunca (spec)."""
    r = rng.random()
    es_regexable = entity in ENTIDADES_CERO_TYPOS or True  # separadores/casing vale para todos
    if r < 0.80 and es_regexable:
        return op_separadores_casing(padre_norm, rng)
    if r < 0.90:
        s, ok = op_abbrev(padre_norm, rng)
        if ok:
            return s
        return op_separadores_casing(padre_norm, rng)
    if r < 0.95:
        return op_calificador(padre_norm, rng)
    return op_sufijo(padre_norm, rng)  # baja proporcion; normalizacion los borra para B


def build_aug(df_norm: pd.DataFrame, cap: int = CAP, seed: int = SEED) -> pd.DataFrame:
    rng = random.Random(seed)
    pos = df_norm[df_norm["entity"].notna()].copy()
    pos = pos[pos["entity"].astype(str) != ""]
    reales_norm = set(pos["name_norm"].dropna().tolist())

    # n distinto real por entidad
    counts = pos.groupby("entity")["name_norm"].nunique().to_dict()
    rows = []
    vistos = set(reales_norm)  # dedup contra reales y entre sinteticos (en espacio name_norm)

    for entity, n_real in counts.items():
        if entity in TIER_1_SIN_SINTETICOS:
            continue
        need = max(0, cap - int(n_real))
        if need <= 0:
            continue
        padres = pos[pos["entity"] == entity]["name_norm"].dropna().unique().tolist()
        if not padres:
            continue
        generados = 0
        intentos = 0
        # round-robin sobre padres para no sesgar a un solo padre
        idx = 0
        while generados < need and intentos < need * 50:
            intentos += 1
            padre = padres[idx % len(padres)]
            idx += 1
            cand = generar_para_padre(str(padre), str(entity), rng)
            cand_norm = normalize_name(cand)
            if not cand_norm or cand_norm in vistos:
                continue
            # guarda forma cruda sintética + parent para agrupar fold
            rows.append({"name": cand, "entity": entity, "is_synthetic": 1, "parent_norm": padre,
                         "_cand_norm": cand_norm})
            vistos.add(cand_norm)
            generados += 1

    aug = pd.DataFrame(rows, columns=["name", "entity", "is_synthetic", "parent_norm"])
    return aug


def main():
    # 1. MODO DATAIKU: sin argparse (el wrapper DSS trae sus propios flags).
    if HAS_DATAIKU:
        df = dataiku.Dataset(IN_NORM).get_dataframe()
        aug = build_aug(df, CAP, SEED)
        dataiku.Dataset(OUT_AUG).write_with_schema(aug)
        print(f"OK 2c: {len(aug)} sinteticos (<1.5% del 21k esperado ~280-300). "
              f"Por entidad: {aug['entity'].value_counts().to_dict() if len(aug) else {}}")
        print("RECORDATORIO: aug solo en train, agrupado por parent_norm, excluido de val/calibracion/umbral.")
        return

    # 2. MODO LOCAL: solo aqui se usa argparse.
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="norm.csv")
    ap.add_argument("--output", default="aug.csv")
    ap.add_argument("--cap", type=int, default=CAP)
    ap.add_argument("--seed", type=int, default=SEED)
    a, _ = ap.parse_known_args()

    df = pd.read_csv(a.input)
    aug = build_aug(df, a.cap, a.seed)
    aug.to_csv(a.output, index=False)
    print(f"OK 2c local: {len(aug)} filas -> {a.output}")


if __name__ == "__main__":
    main()
