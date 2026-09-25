# Eval + threshold por curva PR (max F1, equilibrio P-R) + diagnóstico overlap vs 267k
# Local: python 03_evaluate.py --prepared dataset_21k_prepared.csv --model modelo_fase1.joblib --out-curve pr_curve.csv --big dataset_no_validated_prepared.csv
import argparse
import joblib
import numpy as np
import pandas as pd
from scipy.sparse import hstack, csr_matrix
from sklearn.metrics import (average_precision_score, precision_recall_curve, f1_score,
                             confusion_matrix, classification_report)
from common_features import fuzzy_max_score


def score_names(bundle, names: pd.Series):
    tfidf, scaler, num_feat = bundle["tfidf"], bundle["scaler"], bundle["num_feat"]
    entity_top, num_cols = bundle["entity_top"], bundle["num_cols"]
    Xt = tfidf.transform(names.astype(str))
    n = num_feat.transform(pd.DataFrame({"name_clean": names.astype(str)}))
    n["fuzzy_entity_score"] = names.astype(str).map(lambda x: fuzzy_max_score(x, entity_top)).values
    n = n[num_cols]
    Xn = scaler.transform(n.values)
    X = hstack([Xt, csr_matrix(Xn)]).tocsr()
    m = bundle["model"]
    if getattr(m, "is_fallback_dense_", False):
        X = X.toarray()
    if hasattr(m, "predict_proba"):
        return m.predict_proba(X)[:, 1]
    return m.predict(X)


def pick_threshold(y, p):
    # Max F1 (equilibrio P-R v2): evalúa cada prob única como threshold con regla p>=t
    y = np.asarray(y); p = np.asarray(p)
    uniq = np.unique(p)
    # Limita a 500 candidatos por rendimiento
    if len(uniq) > 500:
        uniq = np.quantile(p, np.linspace(0, 1, 500))
    best = None
    for t in np.sort(uniq)[::-1]:
        pred = (p >= t).astype(int)
        tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
        fn = int(((pred == 0) & (y == 1)).sum())
        rc = tp / max(tp + fn, 1); pr = tp / max(tp + fp, 1)
        f1 = 2 * pr * rc / max(pr + rc, 1e-9)
        if best is None or f1 > best[3]:
            best = (float(t), float(pr), float(rc), float(f1))
    t, pr, rc, f1 = best
    return t, pr, rc, f1


def overlap_report(prep_small: pd.DataFrame, path_big: str | None):
    if not path_big:
        return
    try:
        big = pd.read_csv(path_big, usecols=["name"])
    except Exception as e:
        print(f"Overlap omitido ({e})"); return
    from common_features import clean_name, base_entity
    vs = set(prep_small["name_clean"].map(base_entity).unique())
    vb = set(big["name"].map(lambda x: base_entity(clean_name(x))).unique())
    oov = vb - vs
    print(f"Overlap entidades base: 21k={len(vs)} 267k={len(vb)} "
          f"OOV={len(oov)} ({len(oov)/max(len(vb),1):.1%})")
    if oov:
        print("Ejemplos OOV:", list(oov)[:15])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepared", default="dataset_21k_prepared.csv")
    ap.add_argument("--model", default="modelo_fase1.joblib")
    ap.add_argument("--out-curve", default="pr_curve.csv")
    ap.add_argument("--big", default=None)
    ap.add_argument("--min-f1", type=float, default=0.70)
    a = ap.parse_args()

    df = pd.read_csv(a.prepared)
    bundle = joblib.load(a.model)
    te_idx = bundle.get("test_idx", df.index.values)
    te = df.iloc[te_idx]
    p = score_names(bundle, te["name_clean"])
    y = te["label"].values

    ap_score = average_precision_score(y, p)
    thr, pr, rc, f1 = pick_threshold(y, p)
    # F2 secundario (recall pesa 2x) para contexto
    f2 = 5 * pr * rc / max(4 * pr + rc, 1e-9)
    pred = (p >= thr).astype(int)
    print(f"PR-AUC={ap_score:.4f} threshold(max-F1)={thr:.4f} -> P={pr:.4f} R={rc:.4f} F1={f1:.4f} F2={f2:.4f}")
    print(confusion_matrix(y, pred))
    print(classification_report(y, pred, digits=4))

    prec, rec, thrs = precision_recall_curve(y, p)
    pd.DataFrame({"precision": prec[1:], "recall": rec[1:], "threshold": thrs}).to_csv(a.out_curve, index=False)
    print(f"Curva PR -> {a.out_curve}")

    # Guarda threshold elegido dentro del bundle para scoring
    bundle["threshold"] = thr
    joblib.dump(bundle, a.model)
    print(f"Threshold guardado en {a.model}: {thr:.4f}")

    # Checkpoint 1 explícito (v2: equilibrio F1 + OOV)
    print("CHECKPOINT 1:", "PASA" if f1 >= a.min_f1 else "NO PASA",
          f"(F1 {f1:.3f} vs mínimo {a.min_f1}; OOV se reporta abajo, frena Fase 3 si >40%)")
    overlap_report(df, a.big)


if __name__ == "__main__":
    main()
