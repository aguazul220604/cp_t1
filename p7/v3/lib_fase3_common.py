# Lib Fase 3 — features, modelos, metricas, calibracion (v3 MVP v2).
# Pegar en Dataiku: Library Editor > pii_lib_v3 > fase3_common.py
# Spec: TF-IDF char 2-5 char_wb + word 1-2 sobre name_norm, CV agrupada 3-fold,
# Platt solo con OOF reales, metricas solo reales, umbral por F2.
import numpy as np
import pandas as pd
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score, f1_score, fbeta_score, precision_recall_curve,
)

try:
    import lightgbm as lgb
    HAS_LGBM = True
except ImportError:
    HAS_LGBM = False

# Regularizacion conservadora (spec Fase 3.4).
CHAR_MAX_FEAT = 5000
WORD_MAX_FEAT = 3000
LGBM_BIN_PARAMS = dict(
    n_estimators=300, num_leaves=31, min_child_samples=40,
    colsample_bytree=0.8, reg_lambda=1.0, random_state=42, verbose=-1,
)
LGBM_MULTI_PARAMS = dict(
    n_estimators=400, num_leaves=31, min_child_samples=20,
    colsample_bytree=0.8, reg_lambda=1.0, random_state=42, verbose=-1,
)


def build_vectorizers(train_texts):
    vec_char = TfidfVectorizer(
        analyzer="char_wb", ngram_range=(2, 5),
        min_df=2, max_features=CHAR_MAX_FEAT)
    vec_word = TfidfVectorizer(
        analyzer="word", ngram_range=(1, 2),
        min_df=2, max_features=WORD_MAX_FEAT)
    Xc = vec_char.fit_transform(train_texts)
    Xw = vec_word.fit_transform(train_texts)
    return (vec_char, vec_word), hstack([Xc, Xw]).tocsr()


def apply_vectorizers(vecs, texts):
    vec_char, vec_word = vecs
    return hstack([vec_char.transform(texts),
                   vec_word.transform(texts)]).tocsr()


def make_binary_classifier(scale_pos_weight=1.0):
    if HAS_LGBM:
        return lgb.LGBMClassifier(
            scale_pos_weight=float(scale_pos_weight), **LGBM_BIN_PARAMS)
    # Fallback sin LightGBM (acepta sparse): logistica balanceada.
    # scale_pos_weight se aproxima via class_weight {0:1, 1:spw}.
    from sklearn.linear_model import LogisticRegression as LR
    spw = max(float(scale_pos_weight), 1.0)
    return LR(max_iter=1000, C=1.0,
              class_weight={0: 1.0, 1: spw})


def make_multiclass_classifier():
    if HAS_LGBM:
        return lgb.LGBMClassifier(
            objective="multiclass", **LGBM_MULTI_PARAMS)
    from sklearn.linear_model import LogisticRegression as LR
    return LR(max_iter=1000, C=1.0)


def fit_platt(oof_raw_real, y_real):
    """Calibracion sigmoide (Platt) solo con OOF reales."""
    lr = LogisticRegression()
    lr.fit(np.asarray(oof_raw_real).reshape(-1, 1),
           np.asarray(y_real).astype(int))
    return lr


def apply_platt(calibrador, raw):
    return calibrador.predict_proba(
        np.asarray(raw).reshape(-1, 1))[:, 1]


def scan_threshold(y_true, prob, grid=None):
    """Barre umbrales, devuelve tabla y mejor por F2 (guia recall)."""
    if grid is None:
        grid = np.round(np.arange(0.05, 0.96, 0.05), 2)
    rows = []
    for t in grid:
        pred = (np.asarray(prob) >= float(t)).astype(int)
        # zero_division=0 para colas sin prediccion
        rows.append({
            "umbral": float(t),
            "precision": float((pred & np.asarray(y_true)).sum() / max(pred.sum(), 1)),
            "recall": float((pred & np.asarray(y_true)).sum() / max(np.asarray(y_true).sum(), 1)),
            "f1": float(f1_score(y_true, pred, zero_division=0)),
            "f2": float(fbeta_score(y_true, pred, beta=2, zero_division=0)),
        })
    tab = pd.DataFrame(rows)
    best = tab.loc[tab["f2"].idxmax()]
    return tab, float(best["umbral"]), best.to_dict()


def metrics_binary(y_true, prob, umbral):
    pred = (np.asarray(prob) >= float(umbral)).astype(int)
    return {
        "pr_auc": float(average_precision_score(y_true, prob)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
        "f2": float(fbeta_score(y_true, pred, beta=2, zero_division=0)),
        "umbral": float(umbral),
    }


def metrics_multiclass(y_true, y_pred, labels):
    from sklearn.metrics import f1_score, recall_score
    return {
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "recall_por_entidad": {
            str(l): float(r) for l, r in zip(
                labels,
                recall_score(y_true, y_pred, labels=labels,
                             average=None, zero_division=0))
        },
    }
