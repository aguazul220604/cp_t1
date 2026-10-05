# Dataiku Python recipe: fase2a_normalizacion
# In (Flow):  dataset_validated_labeled  (dataset, name, pii, entity)
#             -- tu dataset actual dataset_validated_prepared_v2_prepared ya etiquetado
#                (renombralo o apunta aqui; debe traer columna `entity`)
# Out (Flow): dataset_validated_norm (mismo + name_norm)
#             deficit_entidades (entity, n_total, n_distinto_norm, need_30, tier)
#
# Local: python recipe_fase2a_normalizacion.py --input labeled.csv --output norm.csv --deficit deficit.csv
import argparse

try:
    import dataiku
    HAS_DATAIKU = True
except ImportError:
    HAS_DATAIKU = False

import pandas as pd

from lib_fase2_normalize import (
    TIER_1_SIN_SINTETICOS, TIER_2_REFUERZO, TIER_3_COMPLETO,
    normalize_name, parse_pii,
)

IN_DATASET = "dataset_validated_labeled"
OUT_DATASET = "dataset_validated_norm"
OUT_DEFICIT = "deficit_entidades"
CAP = 30


def build_norm(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "name" not in df.columns:
        raise ValueError("Se requiere columna `name`")
    df["name_norm"] = df["name"].map(normalize_name)
    # QA: vacios
    df = df[df["name_norm"] != ""].reset_index(drop=True)
    if "pii" in df.columns:
        df["_is_pii"] = parse_pii(df["pii"])
    else:
        df["_is_pii"] = df.get("target", 0).astype(int) == 1
    if "entity" not in df.columns:
        df["entity"] = None
    # entity solo donde pii=TRUE (regla Fase 1.4)
    df.loc[~df["_is_pii"], "entity"] = None
    return df


def build_deficit(df: pd.DataFrame, cap: int = CAP) -> pd.DataFrame:
    pos = df[df["_is_pii"] & df["entity"].notna()].copy()
    g = pos.groupby("entity").agg(
        n_total=("name", "size"),
        n_distinto_norm=("name_norm", "nunique"),
    ).reset_index()

    def tier(e):
        if e in TIER_1_SIN_SINTETICOS:
            return "tier1_sin_sinteticos"
        if e in TIER_2_REFUERZO:
            return "tier2_refuerzo"
        if e in TIER_3_COMPLETO:
            return "tier3_completo"
        return "revisar"

    g["tier"] = g["entity"].map(tier)
    # need solo para tier2/tier3; tier1 -> 0
    g["need_30"] = g.apply(
        lambda r: 0 if r["tier"] == "tier1_sin_sinteticos"
        else max(0, cap - int(r["n_distinto_norm"])),
        axis=1,
    )
    return g.sort_values(["tier", "n_distinto_norm"]).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="labeled.csv")
    ap.add_argument("--output", default="norm.csv")
    ap.add_argument("--deficit", default="deficit.csv")
    ap.add_argument("--cap", type=int, default=CAP)
    a = ap.parse_args()

    if HAS_DATAIKU:
        try:
            df = dataiku.Dataset(IN_DATASET).get_dataframe()
            norm = build_norm(df)
            dataiku.Dataset(OUT_DATASET).write_with_schema(norm.drop(columns=["_is_pii"], errors="ignore"))
            dataiku.Dataset(OUT_DEFICIT).write_with_schema(build_deficit(norm, a.cap))
            print(f"OK 2a: {len(norm)} filas, PII={int(norm['_is_pii'].sum())}, "
                  f"norm_distintos={norm['name_norm'].nunique()}")
            return
        except Exception as e:
            print(f"Dataiku no disponible ({e}), modo local.")

    df = pd.read_csv(a.input)
    norm = build_norm(df)
    norm.drop(columns=["_is_pii"], errors="ignore").to_csv(a.output, index=False)
    build_deficit(norm, a.cap).to_csv(a.deficit, index=False)
    print(f"OK 2a local: {len(norm)} filas -> {a.output}, deficit -> {a.deficit}")


if __name__ == "__main__":
    main()
