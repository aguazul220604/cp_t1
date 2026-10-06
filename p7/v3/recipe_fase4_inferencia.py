# Dataiku Python recipe: fase4_inferencia
# In (Flow):  dataset a puntuar con columna `name` (+ opcional `tabla`/`dataset`).
#             Por defecto: dataset_validated_norm (QA) — para piloto crea `piloto_columnas`.
# Out (Flow): scored_pii (tabla, columna, pii, prob_pii, entity, prob_entity
#             + override_aplicado, regex_match, name_norm)
# Lee artefactos del managed folder fase3_modelos (sin re-entrenar).
# Umbral fijo UMBRAL_ENTITY=0.5 (decision arranque; ver Fase 3).
#
# Local: python recipe_fase4_inferencia.py --input pilot.csv --outdir out4 --artdir out3
import argparse
import json
import os

import pandas as pd

try:
    import dataiku
    HAS_DATAIKU = True
except ImportError:
    HAS_DATAIKU = False

IN_SCORE = "piloto_columnas"   # si no existe, hace fallback a dataset_validated_norm (QA)
IN_SCORE_FALLBACK = "dataset_validated_norm"
OUT_SCORED = "scored_pii"
FOLDER_MODELOS = "fase3_modelos"
UMBRAL_ENTITY = 0.5


def _load_artifacts_local(artdir):
    import joblib
    import glob
    vec_a = joblib.load(os.path.join(artdir, "vec_A.joblib"))
    clf_a = joblib.load(os.path.join(artdir, "modelo_A.joblib"))
    platt = joblib.load(os.path.join(artdir, "platt_A.joblib"))
    umbral_a = json.load(open(os.path.join(artdir, "reporte.json"), encoding="utf-8"))["modelo_A_umbral"] \
        if os.path.exists(os.path.join(artdir, "reporte.json")) else 0.05
    if os.path.exists(os.path.join(artdir, "umbral_A.json")):
        try:
            umbral_a = float(json.load(open(os.path.join(artdir, "umbral_A.json"), encoding="utf-8"))["umbral_A"])
        except Exception:
            pass
    cand_b = sorted(glob.glob(os.path.join(artdir, "vec_B_*.joblib")))
    if not cand_b:
        raise FileNotFoundError("Falta vec_B_*.joblib en " + artdir)
    vec_b = joblib.load(cand_b[0])
    clf_b = joblib.load(cand_b[0].replace("vec_B_", "modelo_B_"))
    clases = json.load(open(os.path.join(artdir, "reporte.json"), encoding="utf-8")).get("clases_B", [])
    return vec_a, clf_a, platt, float(umbral_a), vec_b, clf_b, clases


def main():
    # 1. MODO DATAIKU: sin argparse.
    if HAS_DATAIKU:
        import joblib
        try:
            df = dataiku.Dataset(IN_SCORE).get_dataframe()
        except Exception:
            df = dataiku.Dataset(IN_SCORE_FALLBACK).get_dataframe()
        if "name" not in df.columns:
            # tolera `columna` como alias
            for alt in ("columna", "column", "nombre_columna"):
                if alt in df.columns:
                    df = df.rename(columns={alt: "name"})
                    break
        if "name" not in df.columns:
            raise ValueError("El dataset de entrada debe traer columna `name` (o `columna`).")
        tabla_col = next((c for c in ("tabla", "dataset", "source_file") if c in df.columns), None)
        fpath = dataiku.Folder(FOLDER_MODELOS).get_path()
        vec_a = joblib.load(os.path.join(fpath, "vec_A.joblib"))
        clf_a = joblib.load(os.path.join(fpath, "modelo_A.joblib"))
        platt = joblib.load(os.path.join(fpath, "platt_A.joblib"))
        umbral_a = 0.05
        if os.path.exists(os.path.join(fpath, "umbral_A.json")):
            umbral_a = float(json.load(
                open(os.path.join(fpath, "umbral_A.json"), encoding="utf-8"))["umbral_A"])
        import glob
        cand = sorted(glob.glob(os.path.join(fpath, "vec_B_*.joblib")))
        if not cand:
            raise FileNotFoundError("Falta vec_B_*.joblib en folder " + FOLDER_MODELOS)
        vec_b = joblib.load(cand[0])
        clf_b = joblib.load(cand[0].replace("vec_B_", "modelo_B_"))
        clases = json.load(open(os.path.join(fpath, "clases_B.json"), encoding="utf-8")).get("clases", [])

        try:
            from pii_lib_v3.fase4_infer import predecir_df, UMBRAL_ENTITY as UE
            umb_e = float(UE)
        except ImportError:
            from lib_fase4_infer import predecir_df
            umb_e = float(UMBRAL_ENTITY)
        scored = predecir_df(df[["name"]], vec_a, clf_a, platt, umbral_a,
                             vec_b, clf_b, clases, umb_e)
        scored.insert(0, "tabla", df[tabla_col].astype(str) if tabla_col else "piloto")
        scored.rename(columns={"columna": "columna", "entity_final": "entity",
                               "prob_entity": "prob_entity"}, inplace=True)
        # Formato §4: tabla, columna, pii, prob_pii, entity, prob_entity (+debug)
        keep = ["tabla", "columna", "pii", "prob_pii", "entity", "prob_entity",
                "override_aplicado", "regex_match", "name_norm"]
        # entity final ya quedó en `entity`? predecir_df deja entity ML en `entity`
        # y final en `entity_final`; unificamos a `entity` = final.
        scored["entity"] = scored["entity_final"]
        dataiku.Dataset(OUT_SCORED).write_with_schema(scored[keep])
        print(f"OK 4: {len(scored)} cols, pii={int(scored['pii'].sum())}, "
              f"override={int(scored['override_aplicado'].sum())}")
        return

    # 2. MODO LOCAL
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="pilot.csv")
    ap.add_argument("--outdir", default="out4")
    ap.add_argument("--artdir", default="out3")
    a, _ = ap.parse_known_args()
    os.makedirs(a.outdir, exist_ok=True)
    from lib_fase4_infer import predecir_df
    df = pd.read_csv(a.input)
    if "name" not in df.columns:
        for alt in ("columna", "column"):
            if alt in df.columns:
                df = df.rename(columns={alt: "name"})
                break
    vec_a, clf_a, platt, umbral_a, vec_b, clf_b, _ = _load_artifacts_local(a.artdir)
    scored = predecir_df(df[["name"]], vec_a, clf_a, platt, umbral_a,
                         vec_b, clf_b, [], UMBRAL_ENTITY)
    scored.insert(0, "tabla", df["tabla"].astype(str) if "tabla" in df.columns else "piloto")
    scored["entity"] = scored["entity_final"]
    scored[["tabla", "columna", "pii", "prob_pii", "entity", "prob_entity",
            "override_aplicado", "regex_match", "name_norm"]].to_csv(
        os.path.join(a.outdir, "scored.csv"), index=False)
    print(f"OK 4 local -> {a.outdir}/scored.csv")


if __name__ == "__main__":
    main()
