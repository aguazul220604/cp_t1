# Recipe Dataiku (Python) + local: 21k -> 21k_prepared
# Entrada Dataiku: dataset_validated_prepared (dataset,name,pii,target)
# Salida Dataiku: dataset_21k_prepared
# Local: python 01_prepare.py --input validated.csv --output prepared.csv
import argparse
import pandas as pd

try:
    import dataiku
    HAS_DATAIKU = True
except ImportError:
    HAS_DATAIKU = False

from common_features import clean_name, base_entity


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # Normaliza nombre de columna fuente
    col = "name" if "name" in df.columns else df.columns[0]
    df["name_clean"] = df[col].map(clean_name)
    df["base_entity"] = df["name_clean"].map(base_entity)
    df["longitud"] = df["name_clean"].str.len()
    # Label canónico: usa `target` si existe, si no `pii`
    if "target" in df.columns:
        df["label"] = df["target"].astype(int)
    elif "pii" in df.columns:
        df["label"] = (df["pii"].astype(str).str.lower().isin(["1", "true", "si", "pii", "yes"])).astype(int)
    else:
        raise ValueError("Se requiere columna `target` o `pii`")
    # Filtra vacíos
    df = df[df["name_clean"] != ""].reset_index(drop=True)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="dataset_validated_prepared.csv")
    ap.add_argument("--output", default="dataset_21k_prepared.csv")
    a = ap.parse_args()

    if HAS_DATAIKU:
        try:
            inp = dataiku.Dataset("dataset_validated_prepared")
            df = inp.get_dataframe()
            out = prepare(df)
            dataiku.Dataset("dataset_21k_prepared").write_with_schema(out)
            print(f"OK prepare: {len(out)} filas, PII rate={out['label'].mean():.4f}")
            return
        except Exception as e:
            print(f"Dataiku no disponible ({e}), modo local.")

    df = pd.read_csv(a.input)
    out = prepare(df)
    out.to_csv(a.output, index=False)
    print(f"OK prepare local: {len(out)} filas -> {a.output}, PII rate={out['label'].mean():.4f}")


if __name__ == "__main__":
    main()
