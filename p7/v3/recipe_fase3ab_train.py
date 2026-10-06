# Dataiku Python recipe: fase3ab_train
# In (Flow):  dataset_validated_norm (name, name_norm, pii, entity)
#             aug_train_only (name, entity, is_synthetic=1, parent_norm)
# Out (Flow): oof_pred_A (name, name_norm, y_true, oof_raw, oof_cal, fold)
#             oof_pred_B (name, name_norm, y_true_entity, pred_base, pred_aug, fold)
#             reporte_fase3 (metric, variant, value)
#             + managed folder fase3_modelos:
#               vec_A.joblib, modelo_A.joblib, platt_A.joblib, umbral_A.json,
#               vec_B_<ganador>.joblib, modelo_B_<ganador>.joblib, clases_B.json,
#               reporte.json, oof_A.csv, oof_B.csv
#
# Spec Fase 3: CV 3-fold agrupada name_norm(+parent_norm), sinteticos solo train,
# scale_pos_weight en A, Platt + umbral F2 solo con OOF reales,
# A: PR-AUC/F1/F2, B: Macro-F1 + recall cola, decision B_base vs B_aug.
#
# Local: python recipe_fase3ab_train.py --norm norm.csv --aug aug.csv --outdir out3
import argparse
import io
import json

import numpy as np
import pandas as pd

try:
    import dataiku
    HAS_DATAIKU = True
except ImportError:
    HAS_DATAIKU = False

try:
    # DSS Library Editor: pii_lib_v3 > fase3_common.py / normalize_v3.py
    from pii_lib_v3.fase3_common import (
        apply_platt, apply_vectorizers, build_vectorizers, fit_platt,
        make_binary_classifier, make_multiclass_classifier,
        metrics_binary, metrics_multiclass, scan_threshold,
    )
    from pii_lib_v3.normalize_v3 import normalize_name, parse_pii
except ImportError:
    from lib_fase3_common import (
        apply_platt, apply_vectorizers, build_vectorizers, fit_platt,
        make_binary_classifier, make_multiclass_classifier,
        metrics_binary, metrics_multiclass, scan_threshold,
    )
    from lib_fase2_normalize import normalize_name, parse_pii

IN_NORM = "dataset_validated_norm"
IN_AUG = "aug_train_only"
OUT_OOF_A = "oof_pred_A"
OUT_OOF_B = "oof_pred_B"
OUT_REPORT = "reporte_fase3"
OUT_FOLDER = "fase3_modelos"
N_SPLITS = 3


def _prep_norm(df):
    df = df.copy()
    if "name_norm" not in df.columns or df["name_norm"].isna().all():
        df["name_norm"] = df["name"].map(normalize_name)
    df["name_norm"] = df["name_norm"].fillna("").astype(str)
    df = df[df["name_norm"] != ""].reset_index(drop=True)
    if "pii" in df.columns:
        df["_y"] = parse_pii(df["pii"]).astype(int)
    else:
        df["_y"] = df.get("target", 0).astype(int)
    if "entity" not in df.columns:
        df["entity"] = None
    df.loc[df["_y"] == 0, "entity"] = None
    df["_group"] = df["name_norm"]
    df["_is_real"] = True
    return df


def _prep_aug(df):
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["name", "name_norm", "entity", "parent_norm"])
    df = df.copy()
    df["name_norm"] = df["name"].map(normalize_name)
    df = df[df["name_norm"] != ""].reset_index(drop=True)
    # grupo del hijo = parent_norm (mismo fold que el padre real)
    df["_group"] = df.get("parent_norm", df["name_norm"]).fillna(df["name_norm"])
    df["_y"] = 1  # todo sintetico es PII (solo-train)
    df["_is_real"] = False
    return df


def run_fase3(df_norm, df_aug, n_splits=N_SPLITS):
    from sklearn.model_selection import GroupKFold
    real = _prep_norm(df_norm)
    aug = _prep_aug(df_aug)

    # ---------- Modelo A ----------
    y_real = real["_y"].values
    groups_a = real["_group"].values
    n_groups = len(np.unique(groups_a))
    n_splits_a = min(n_splits, max(2, n_groups))
    gkf_a = GroupKFold(n_splits=n_splits_a)
    oof_raw = np.full(len(real), np.nan)
    fold_col = np.full(len(real), -1)

    for fold, (tr, va) in enumerate(gkf_a.split(real, y_real, groups_a)):
        tr_groups = set(groups_a[tr])
        # sinteticos cuyo padre esta en train (evita fuga)
        aug_tr = aug[aug["_group"].isin(tr_groups)] if len(aug) else aug
        train_texts = pd.concat(
            [real.iloc[tr]["name_norm"], aug_tr["name_norm"]],
            ignore_index=True).tolist() if len(aug_tr) else real.iloc[tr]["name_norm"].tolist()
        vecs, Xtr = build_vectorizers(train_texts)
        # filas train reales -> Xtr[:len(tr)]; sinteticas despues
        n_tr_real = len(tr)
        Xva = apply_vectorizers(vecs, real.iloc[va]["name_norm"].tolist())
        y_tr = np.concatenate(
            [real.iloc[tr]["_y"].values, aug_tr["_y"].values]) if len(aug_tr) else real.iloc[tr]["_y"].values
        n_neg = int((y_tr == 0).sum())
        n_pos = max(int((y_tr == 1).sum()), 1)
        clf = make_binary_classifier(scale_pos_weight=n_neg / n_pos)
        # Xtr ya incluye reales+sint; y_tr alineado
        clf.fit(Xtr, y_tr)
        oof_raw[va] = clf.predict_proba(Xva)[:, 1]
        fold_col[va] = fold
        # guarda vecs/clf del ultimo fold solo para debug; el final se reentrena abajo
        last_vecs, last_clf = vecs, clf

    # Calibracion Platt SOLO con OOF reales (todos los reales son reales aqui)
    mask = ~np.isnan(oof_raw)
    platt = fit_platt(oof_raw[mask], y_real[mask])
    oof_cal = apply_platt(platt, oof_raw)
    tab_umbral, umbral_a, _ = scan_threshold(y_real[mask], oof_cal[mask])
    met_a = metrics_binary(y_real[mask], oof_cal[mask], umbral_a)

    oofA = real[["name", "name_norm", "entity"]].copy()
    oofA["y_true"] = y_real
    oofA["oof_raw"] = np.round(oof_raw, 4)
    oofA["oof_cal"] = np.round(oof_cal, 4)
    oofA["fold"] = fold_col

    # ---------- Modelo B (solo pii=TRUE reales) ----------
    pii_real = real[real["_y"] == 1].reset_index(drop=True)
    clases = sorted([c for c in pii_real["entity"].dropna().unique().tolist() if str(c) != ""])
    yb = pii_real["entity"].values
    groups_b = pii_real["_group"].values
    n_groups_b = len(np.unique(groups_b))
    n_splits_b = min(n_splits, max(2, n_groups_b))
    gkf_b = GroupKFold(n_splits=n_splits_b)
    oof_base = np.empty(len(pii_real), dtype=object)
    oof_aug = np.empty(len(pii_real), dtype=object)

    for fold, (tr, va) in enumerate(gkf_b.split(pii_real, yb, groups_b)):
        tr_groups = set(groups_b[tr])
        aug_tr = aug[aug["entity"].isin(clases) & aug["_group"].isin(tr_groups)] if len(aug) else aug.iloc[0:0]
        # --- B_base: solo reales ---
        vecs_b, Xtr_b = build_vectorizers(pii_real.iloc[tr]["name_norm"].tolist())
        Xva_b = apply_vectorizers(vecs_b, pii_real.iloc[va]["name_norm"].tolist())
        clf_b = make_multiclass_classifier()
        clf_b.fit(Xtr_b, pii_real.iloc[tr]["entity"].values)
        oof_base[va] = clf_b.predict(Xva_b)
        # --- B_aug: reales + sinteticos en train ---
        if len(aug_tr):
            txt_aug = pd.concat(
                [pii_real.iloc[tr]["name_norm"], aug_tr["name_norm"]],
                ignore_index=True).tolist()
            vecs_a, Xtr_a = build_vectorizers(txt_aug)
            y_aug = pd.concat(
                [pii_real.iloc[tr]["entity"], aug_tr["entity"]],
                ignore_index=True).values
            Xva_a = apply_vectorizers(vecs_a, pii_real.iloc[va]["name_norm"].tolist())
            clf_a = make_multiclass_classifier()
            clf_a.fit(Xtr_a, y_aug)
            oof_aug[va] = clf_a.predict(Xva_a)
        else:
            oof_aug[va] = oof_base[va]

    met_b_base = metrics_multiclass(yb, oof_base, clases)
    met_b_aug = metrics_multiclass(yb, oof_aug, clases)
    ganador = "aug" if met_b_aug["macro_f1"] >= met_b_base["macro_f1"] else "base"

    oofB = pii_real[["name", "name_norm"]].copy()
    oofB["y_true_entity"] = yb
    oofB["pred_base"] = oof_base
    oofB["pred_aug"] = oof_aug
    oofB["fold"] = -1
    # rellenar folds B
    for fold, (_, va) in enumerate(gkf_b.split(pii_real, yb, groups_b)):
        oofB.iloc[va, oofB.columns.get_loc("fold")] = fold

    reporte = {
        "modelo_A_pr_auc": met_a["pr_auc"], "modelo_A_f1": met_a["f1"],
        "modelo_A_f2": met_a["f2"], "modelo_A_umbral": umbral_a,
        "modelo_B_base_macro_f1": met_b_base["macro_f1"],
        "modelo_B_aug_macro_f1": met_b_aug["macro_f1"],
        "modelo_B_ganador": ganador,
        "modelo_B_base_recall_cola": met_b_base["recall_por_entidad"],
        "modelo_B_aug_recall_cola": met_b_aug["recall_por_entidad"],
        "n_reales": int(len(real)), "n_pii_reales": int((real["_y"] == 1).sum()),
        "n_sinteticos": int(len(aug)), "n_splits_A": int(n_splits_a),
        "n_splits_B": int(n_splits_b), "clases_B": clases,
    }
    extras = {"tab_umbral_A": tab_umbral, "platt": platt,
              "oof_raw_A": oof_raw, "oof_cal_A": oof_cal}
    return oofA, oofB, reporte, extras, real, aug, clases, umbral_a


def train_finales(real, aug, clases, umbral_a):
    """Reentrena vectores+modelos en FULL (reales + sinteticos en train)."""
    # A final
    txt_a = pd.concat([real["name_norm"], aug["name_norm"]],
                      ignore_index=True).tolist() if len(aug) else real["name_norm"].tolist()
    vecs_a, Xa = build_vectorizers(txt_a)
    y_a = np.concatenate([real["_y"].values, aug["_y"].values]) if len(aug) else real["_y"].values
    clf_a = make_binary_classifier(
        scale_pos_weight=int((y_a == 0).sum()) / max(int((y_a == 1).sum()), 1))
    clf_a.fit(Xa, y_a)
    # B final (ganador se decide fuera; aqui se entrenan ambos y se elige al guardar)
    pii_real = real[real["_y"] == 1].reset_index(drop=True)
    vecs_bb, Xbb = build_vectorizers(pii_real["name_norm"].tolist())
    clf_bb = make_multiclass_classifier()
    clf_bb.fit(Xbb, pii_real["entity"].values)
    vecs_ba, Xba, clf_ba = vecs_bb, Xbb, clf_bb
    if len(aug):
        aug_b = aug[aug["entity"].isin(clases)]
        txt_ba = pd.concat([pii_real["name_norm"], aug_b["name_norm"]],
                           ignore_index=True).tolist()
        vecs_ba, Xba = build_vectorizers(txt_ba)
        y_ba = pd.concat([pii_real["entity"], aug_b["entity"]],
                         ignore_index=True).values
        clf_ba = make_multiclass_classifier()
        clf_ba.fit(Xba, y_ba)
    return (vecs_a, clf_a), (vecs_bb, clf_bb), (vecs_ba, clf_ba)


def to_report_df(reporte):
    rows = []
    for k, v in reporte.items():
        if isinstance(v, (dict, list)):
            rows.append({"metric": k, "variant": "json", "value": json.dumps(v, ensure_ascii=False)})
        else:
            rows.append({"metric": k, "variant": "value", "value": v})
    return pd.DataFrame(rows, columns=["metric", "variant", "value"])


def main():
    # 1. MODO DATAIKU: sin argparse.
    if HAS_DATAIKU:
        df_norm = dataiku.Dataset(IN_NORM).get_dataframe()
        try:
            df_aug = dataiku.Dataset(IN_AUG).get_dataframe()
        except Exception:
            df_aug = pd.DataFrame()
        oofA, oofB, reporte, extras, real, aug, clases, umbral_a = run_fase3(df_norm, df_aug)
        dataiku.Dataset(OUT_OOF_A).write_with_schema(oofA)
        dataiku.Dataset(OUT_OOF_B).write_with_schema(oofB)
        dataiku.Dataset(OUT_REPORT).write_with_schema(to_report_df(reporte))
        # Finales + guardado en folder
        import joblib
        (vecs_a, clf_a), (vecs_bb, clf_bb), (vecs_ba, clf_ba) = train_finales(real, aug, clases, umbral_a)
        g = reporte["modelo_B_ganador"]
        vecs_b, clf_b = (vecs_ba, clf_ba) if g == "aug" else (vecs_bb, clf_bb)
        folder = dataiku.Folder(OUT_FOLDER)
        for name, obj in [("vec_A.joblib", vecs_a), ("modelo_A.joblib", clf_a),
                          ("platt_A.joblib", extras["platt"]),
                          (f"vec_B_{g}.joblib", vecs_b), (f"modelo_B_{g}.joblib", clf_b)]:
            buf = io.BytesIO()
            joblib.dump(obj, buf)
            folder.upload_data(name, buf.getvalue())
        folder.upload_data("umbral_A.json",
                           json.dumps({"umbral_A": umbral_a}, indent=2).encode("utf-8"))
        folder.upload_data("clases_B.json",
                           json.dumps({"clases": clases, "ganador": g}, ensure_ascii=False, indent=2).encode("utf-8"))
        folder.upload_data("reporte.json",
                           json.dumps(reporte, ensure_ascii=False, indent=2, default=str).encode("utf-8"))
        print(f"OK 3: A pr_auc={reporte['modelo_A_pr_auc']:.3f} f1={reporte['modelo_A_f1']:.3f} "
              f"f2={reporte['modelo_A_f2']:.3f} umbral={umbral_a} | "
              f"B_base={reporte['modelo_B_base_macro_f1']:.3f} B_aug={reporte['modelo_B_aug_macro_f1']:.3f} "
              f"ganador={g}")
        return

    # 2. MODO LOCAL
    ap = argparse.ArgumentParser()
    ap.add_argument("--norm", default="norm.csv")
    ap.add_argument("--aug", default="aug.csv")
    ap.add_argument("--outdir", default="out3")
    a, _ = ap.parse_known_args()
    import joblib
    import os
    df_norm = pd.read_csv(a.norm)
    try:
        df_aug = pd.read_csv(a.aug)
    except Exception:
        df_aug = pd.DataFrame()
    oofA, oofB, reporte, extras, real, aug, clases, umbral_a = run_fase3(df_norm, df_aug)
    os.makedirs(a.outdir, exist_ok=True)
    oofA.to_csv(f"{a.outdir}/oof_A.csv", index=False)
    oofB.to_csv(f"{a.outdir}/oof_B.csv", index=False)
    to_report_df(reporte).to_csv(f"{a.outdir}/reporte.csv", index=False)
    (vecs_a, clf_a), (vecs_bb, clf_bb), (vecs_ba, clf_ba) = train_finales(real, aug, clases, umbral_a)
    g = reporte["modelo_B_ganador"]
    vecs_b, clf_b = (vecs_ba, clf_ba) if g == "aug" else (vecs_bb, clf_bb)
    joblib.dump(vecs_a, f"{a.outdir}/vec_A.joblib")
    joblib.dump(clf_a, f"{a.outdir}/modelo_A.joblib")
    joblib.dump(extras["platt"], f"{a.outdir}/platt_A.joblib")
    joblib.dump(vecs_b, f"{a.outdir}/vec_B_{g}.joblib")
    joblib.dump(clf_b, f"{a.outdir}/modelo_B_{g}.joblib")
    with open(f"{a.outdir}/reporte.json", "w", encoding="utf-8") as f:
        json.dump(reporte, f, ensure_ascii=False, indent=2, default=str)
    print(f"OK 3 local -> {a.outdir}: umbral={umbral_a} ganador_B={g}")


if __name__ == "__main__":
    main()
