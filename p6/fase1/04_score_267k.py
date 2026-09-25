# Scoring del 267k con modelo Fase 1 -> pii_validated/prob (NO sobrescribe pii)
# Local: python 04_score_267k.py --model modelo_fase1.joblib --input dataset_no_validated_prepared.csv --output dataset_no_validated_enriquecido.csv
import argparse
import joblib
import pandas as pd
from scipy.sparse import hstack, csr_matrix

try:
    import dataiku
    HAS_DATAIKU = True
except ImportError:
    HAS_DATAIKU = False

from common_features import clean_name, base_entity, fuzzy_max_score
from entity_taxonomy import predict_entity


def score_df(bundle, df: pd.DataFrame, col="name"):
    names = df[col].map(clean_name)
    tfidf, scaler, num_feat = bundle["tfidf"], bundle["scaler"], bundle["num_feat"]
    Xt = tfidf.transform(names)
    n = num_feat.transform(pd.DataFrame({"name_clean": names}))
    n["fuzzy_entity_score"] = names.map(lambda x: fuzzy_max_score(x, bundle["entity_top"])).values
    n = n[bundle["num_cols"]]
    X = hstack([Xt, csr_matrix(scaler.transform(n.values))]).tocsr()
    m = bundle["model"]
    if getattr(m, "is_fallback_dense_", False):
        X = X.toarray()
    p = m.predict_proba(X)[:, 1] if hasattr(m, "predict_proba") else m.predict(X)
    return names, p


def enrich(df: pd.DataFrame, bundle) -> pd.DataFrame:
    thr = float(bundle.get("threshold", 0.5))
    names, p = score_df(bundle, df, "name")
    out = df.copy()
    out["name_clean"] = names
    out["base_entity"] = names.map(base_entity)
    out["prob_pii_validated"] = p
    out["pii_validated"] = (p >= thr).astype(int)
    # Entidad independiente del PII: numtel y tel casa1 -> TELEFONO; tel casa ict1 -> TELEFONO pero pii=0
    ent = names.map(predict_entity)
    out["entity"] = [e[0] for e in ent]
    out["prob_entity"] = [e[1] for e in ent]
    # Bandera de revisión, no sobrescritura (Fase 3 del plan)
    if "pii" in out.columns:
        out["discrepancia"] = (out["pii_validated"] != out["pii"].astype(int)).astype(int)
    out["threshold_aplicado"] = thr
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="modelo_fase1.joblib")
    ap.add_argument("--input", default="dataset_no_validated_prepared.csv")
    ap.add_argument("--output", default="dataset_no_validated_enriquecido.csv")
    a = ap.parse_args()

    if HAS_DATAIKU:
        try:
            bundle = joblib.load("modelo_fase1.joblib")  # o leer de managed folder
        except Exception:
            import io
            buf = dataiku.Folder("model_fase1").get_download_stream("modelo_fase1.joblib").read()
            import joblib as jl
            bundle = jl.load(io.BytesIO(buf))
        df = dataiku.Dataset("dataset_no_validated_prepared").get_dataframe()
        out = enrich(df, bundle)
        dataiku.Dataset("dataset_no_validated_enriquecido").write_with_schema(out)
        print(f"OK score Dataiku: {len(out)} filas, discrepancias={out['discrepancia'].mean():.3%}")
        return

    bundle = joblib.load(a.model)
    df = pd.read_csv(a.input)
    out = enrich(df, bundle)
    out.to_csv(a.output, index=False)
    print(f"OK score local -> {a.output} threshold={bundle.get('threshold',0.5):.4f}")


if __name__ == "__main__":
    main()
