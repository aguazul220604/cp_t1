# Recipe Dataiku (Python) + local: entrena LightGBM solo-name sobre 21k_prepared
# Guarda: modelo.joblib (TF-IDF + scaler + booster + entity_top + threshold por defecto)
# Uso Dataiku: entrada dataset_21k_prepared, salida carpeta managed `model_fase1`
# Local: python 02_train.py --input dataset_21k_prepared.csv --model modelo_fase1.joblib --test-size 0.3
import argparse
import joblib
import numpy as np
import pandas as pd
from scipy.sparse import hstack, csr_matrix
from sklearn.model_selection import StratifiedGroupKFold, train_test_split
from sklearn.preprocessing import StandardScaler

try:
    import dataiku
    HAS_DATAIKU = True
except ImportError:
    HAS_DATAIKU = False

from common_features import (
    SEED, build_tfidf, NameNumericFeatures, add_fuzzy_feature, base_entity,
)

try:
    import lightgbm as lgb
    HAS_LGBM = True
except ImportError:
    HAS_LGBM = False
    from sklearn.ensemble import HistGradientBoostingClassifier


def make_groups(df: pd.DataFrame):
    # Agrupa variantes del mismo base_entity + dataset para evitar leakage en split/CV
    g = df["base_entity"].fillna("") + "||" + df.get("dataset", pd.Series("", index=df.index)).astype(str)
    return g


def fit_model(X_tr, y_tr, X_va, y_va):
    pos = int((y_tr == 1).sum())
    neg = int((y_tr == 0).sum())
    spw = neg / max(pos, 1)
    print(f"train pos={pos} neg={neg} scale_pos_weight={spw:.1f}")
    if HAS_LGBM:
        dtr = lgb.Dataset(X_tr, label=y_tr)
        dva = lgb.Dataset(X_va, label=y_va, reference=dtr)
        params = dict(
            objective="binary", metric="average_precision",
            num_leaves=31, min_data_in_leaf=50, feature_fraction=0.8,
            bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0,
            learning_rate=0.05, scale_pos_weight=spw, verbose=-1, seed=SEED,
        )
        model = lgb.train(params, dtr, num_boost_round=2000,
                          valid_sets=[dva], callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)])
    else:
        print("WARN: lightgbm no instalado, fallback HistGradientBoosting.")
        from scipy.sparse import issparse
        Xt_tr = X_tr.toarray() if issparse(X_tr) else X_tr
        model = HistGradientBoostingClassifier(
            max_iter=500, learning_rate=0.05, max_leaf_nodes=31,
            min_samples_leaf=50, l2_regularization=1.0,
            class_weight={0: 1.0, 1: spw}, random_state=SEED,
        )
        model.fit(Xt_tr, y_tr)
        model.is_fallback_dense_ = True
    return model


def train(df: pd.DataFrame, test_size=0.3):
    df = df.copy().reset_index(drop=True)
    groups = make_groups(df)

    # Split estratificado con grupos: aproximación en 2 pasos (group-aware + strat check)
    # 1) split por grupos únicos ponderando label mayoritario del grupo
    gdf = pd.DataFrame({"g": groups, "y": df["label"]}).groupby("g")["y"].agg(
        y_mean="mean", y_max="max", n="size").reset_index()
    gdf["glabel"] = (gdf["y_mean"] >= 0.5).astype(int)
    g_tr, g_te = train_test_split(
        gdf["g"], test_size=test_size, random_state=SEED, stratify=gdf["glabel"])
    tr_mask = groups.isin(set(g_tr)).values
    te_mask = ~tr_mask
    print(f"split train={tr_mask.sum()} test={te_mask.sum()} "
          f"PII train={df.loc[tr_mask,'label'].mean():.4f} test={df.loc[te_mask,'label'].mean():.4f}")

    # Sub-split train -> train/valid para early stopping (estratificado simple)
    idx_tr = np.where(tr_mask)[0]
    y_tr_full = df.loc[tr_mask, "label"].values
    i_tr, i_va = train_test_split(idx_tr, test_size=0.2, random_state=SEED, stratify=y_tr_full)

    num_feat = NameNumericFeatures()
    num_feat.fit(df.iloc[i_tr], df.iloc[i_tr]["label"].values)
    entity_top = num_feat.entity_top_

    tfidf = build_tfidf()
    X_tfidf_tr = tfidf.fit_transform(df.iloc[i_tr]["name_clean"])
    X_tfidf_va = tfidf.transform(df.iloc[i_va]["name_clean"])
    X_tfidf_te = tfidf.transform(df.iloc[te_mask]["name_clean"])

    scaler = StandardScaler(with_mean=False)
    def num_mat(idx):
        n = num_feat.transform(df.iloc[idx])
        fz = df.iloc[idx]["name_clean"].map(
            lambda x: __import__("common_features").fuzzy_max_score(x, entity_top))
        n["fuzzy_entity_score"] = fz.values
        return scaler.fit_transform(n.values) if idx is i_tr else scaler.transform(n.values)

    # fit scaler solo en train
    n_tr_df = num_feat.transform(df.iloc[i_tr])
    n_tr_df["fuzzy_entity_score"] = df.iloc[i_tr]["name_clean"].map(
        lambda x: __import__("common_features").fuzzy_max_score(x, entity_top)).values
    scaler.fit(n_tr_df.values)
    import numpy as _np
    X_num_tr = scaler.transform(n_tr_df.values)
    n_va = num_feat.transform(df.iloc[i_va]); n_va["fuzzy_entity_score"] = df.iloc[i_va]["name_clean"].map(lambda x: __import__("common_features").fuzzy_max_score(x, entity_top)).values
    n_te = num_feat.transform(df.iloc[te_mask]); n_te["fuzzy_entity_score"] = df.iloc[te_mask]["name_clean"].map(lambda x: __import__("common_features").fuzzy_max_score(x, entity_top)).values
    X_num_va = scaler.transform(n_va.values); X_num_te = scaler.transform(n_te.values)

    X_tr = hstack([X_tfidf_tr, csr_matrix(X_num_tr)]).tocsr()
    X_va = hstack([X_tfidf_va, csr_matrix(X_num_va)]).tocsr()
    X_te = hstack([X_tfidf_te, csr_matrix(X_num_te)]).tocsr()

    model = fit_model(X_tr, df.iloc[i_tr]["label"].values, X_va, df.iloc[i_va]["label"].values)

    bundle = dict(model=model, tfidf=tfidf, scaler=scaler, num_feat=num_feat,
                  entity_top=entity_top, num_cols=list(n_tr_df.columns),
                  test_idx=np.where(te_mask)[0], seed=SEED)
    return bundle, df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="dataset_21k_prepared.csv")
    ap.add_argument("--model", default="modelo_fase1.joblib")
    ap.add_argument("--test-size", type=float, default=0.3)
    a = ap.parse_args()

    if HAS_DATAIKU:
        try:
            df = dataiku.Dataset("dataset_21k_prepared").get_dataframe()
            bundle, _ = train(df, test_size=a.test_size)
            folder = dataiku.Folder("model_fase1")
            import io
            with folder.get_writer("modelo_fase1.joblib") as w:
                buf = io.BytesIO(); joblib.dump(bundle, buf); w.write(buf.getvalue())
            print("OK train Dataiku -> folder model_fase1/modelo_fase1.joblib")
            return
        except Exception as e:
            print(f"Dataiku no disponible ({e}), modo local.")

    df = pd.read_csv(a.input)
    bundle, _ = train(df, test_size=a.test_size)
    joblib.dump(bundle, a.model)
    print(f"OK train local -> {a.model}")


if __name__ == "__main__":
    main()
