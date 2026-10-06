# Dataiku Python recipe: fase2_juez_v3 (Juez 23 sobre gold_v2 con pesos)
# Input (Flow):  gold_v2 (name, entity, label_source, w) — gold 1.0 + pool 0.5
# Output (Flow): managed folder fase2_juez_v3 (modelo.txt, vectorizer.pkl,
#                clases.json, calibrador.pkl, metricas.html)
# Hereda fixes v2 (labels F1 23, GroupKFold dinamico, fallback lineal,
# FrozenEstimator) + sample_weight en fit y calibracion.
# Requiere pii_lib/juez_v2.py + lightgbm en el code env.
import json
import os
import pickle

import dataiku
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
try:
    from pii_lib.juez_v2 import (aplicar_fallback, aumentar_raras,
                                 preparar_juez_supervisado)
except ImportError:
    from pii_lib.juez import (aplicar_fallback, aumentar_raras,
                              preparar_juez_supervisado)
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GroupKFold

UMBRAL_FALLBACK = 0.50
N_OBJETIVO_RARAS = 15

print("JUEZ_V3_FIX2")
df = dataiku.Dataset("gold_v2").get_dataframe()
df.columns = [str(c).strip() for c in df.columns]
print(f"gold_v2 cols={list(df.columns)}")
# Lookups defensivos: nunca indexar columnas que pueden no existir
w_map = {}
ls_map = {}
if "name" in df.columns:
    _w = df["w"] if "w" in df.columns else pd.Series(1.0, index=df.index)
    _ls = df["label_source"] if "label_source" in df.columns else None
    for n, wi in zip(df["name"].astype(str), _w.fillna(1.0).tolist()):
        w_map.setdefault(str(n).strip(), float(wi))
    if _ls is not None:
        for n, li in zip(df["name"].astype(str), _ls.fillna("gold_validado").tolist()):
            ls_map.setdefault(str(n).strip(), str(li))
base, info = preparar_juez_supervisado(df, target_col="entity", min_ejemplos=2)
print(f"clases={len(info['clases'])} n={info['n']} eliminadas={info['eliminadas']}")
print(f"soporte={info['soporte']}")
_meta_src = [ls_map.get(str(n).strip(), "gold_validado")
             for n in base["name"].tolist()]
print("mix:\n" + pd.DataFrame(
    {"label_source": _meta_src, "entity": base["entity"].tolist()}
).groupby(["label_source", "entity"]).size().to_string())

# Alinea pesos al orden de base (preparar conserva orden de filas validas)
w_base = np.array([w_map.get(str(n).strip(), 1.0) for n in base["name"].tolist()],
                  dtype=float)

X_txt = base["light"].fillna("").tolist()
y_lab, clases = pd.factorize(base["entity"])
clases = list(clases)
groups = base["group_id"].values

vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
X = vec.fit_transform(X_txt)

# Aumento de raras heredando el peso de la fila origen (pool 0.5 no domina)
Xa_txt, ya_str, wa = [], [], []
s = pd.Series(base["entity"].tolist())
rng = np.random.RandomState(0)
Xa_txt = list(X_txt)
ya_str = list(base["entity"].tolist())
wa = list(w_base)
for cls, n in s.value_counts().items():
    need = int(N_OBJETIVO_RARAS - n)
    if need <= 0:
        continue
    idx_pool = [i for i, y in enumerate(base["entity"].tolist()) if y == cls]
    for _ in range(need):
        i = idx_pool[rng.randint(len(idx_pool))]
        t = X_txt[i]
        v = rng.choice(["nospace", "suf1", "suf2", "undersc", "same"])
        import re as _re
        if v == "nospace":
            t2 = _re.sub(r"[\s\-_]", "", t)
        elif v == "undersc":
            t2 = _re.sub(r"\s+", "_", t)
        elif v == "suf1":
            t2 = f"{t} {rng.randint(1, 9)}"
        elif v == "suf2":
            t2 = f"{t}{rng.randint(1, 99)}"
        else:
            t2 = t
        Xa_txt.append(t2)
        ya_str.append(cls)
        wa.append(float(w_base[i]))
Xa = vec.transform(Xa_txt)
ya = pd.Series(ya_str).map({c: i for i, c in enumerate(clases)}).values
wa = np.asarray(wa, dtype=float)

min_groups = int(base.groupby("entity")["group_id"].nunique().min())
n_splits = max(2, min(5, min_groups))
print(f"n_splits={n_splits} (min_groups={min_groups})")
gkf = GroupKFold(n_splits=n_splits)

import re as _re
ga_txt = [_re.sub(r"[\s\-_]", "", _re.sub(r"\s*\d+$", "", t)).strip() for t in Xa_txt]
w_orig = w_base

accs, f1s, per_class = [], [], {}
oof_true, oof_pred = [], []
for tr, va in gkf.split(X, y_lab, groups):
    tr_groups = set(groups[tr])
    tr_aug = [i for i, g in enumerate(ga_txt[len(X_txt):]) if g in tr_groups]
    tr_idx = list(tr) + [len(X_txt) + i for i in tr_aug]
    Xtr, ytr, wtr = Xa[tr_idx], ya[tr_idx], wa[tr_idx]
    if len(set(ytr.tolist())) < len(clases):
        from sklearn.linear_model import LogisticRegression
        clf = LogisticRegression(class_weight="balanced", max_iter=1000)
        clf.fit(Xtr, ytr, sample_weight=wtr)
        pr = clf.predict(X[va])
    else:
        clf = LGBMClassifier(objective="multiclass", num_class=len(clases),
                             class_weight="balanced", num_leaves=15,
                             min_child_samples=5, n_estimators=400,
                             learning_rate=0.05, verbose=-1, random_state=0)
        clf.fit(Xtr, ytr, sample_weight=wtr)
        try:
            from sklearn.frozen import FrozenEstimator
            cal = CalibratedClassifierCV(FrozenEstimator(clf),
                                         method="sigmoid", cv="prefit")
        except ImportError:
            cal = CalibratedClassifierCV(clf, method="sigmoid", cv="prefit")
        cal.fit(X[tr], y_lab[tr], sample_weight=w_orig[tr])
        pr = cal.predict(X[va])
    accs.append(accuracy_score(y_lab[va], pr))
    f1s.append(f1_score(y_lab[va], pr, average="macro", zero_division=0))
    oof_true.extend(y_lab[va].tolist())
    oof_pred.extend(pr.tolist())
    f1c = f1_score(y_lab[va], pr, labels=list(range(len(clases))),
                   average=None, zero_division=0)
    for i, c in enumerate(clases):
        per_class.setdefault(c, []).append(round(float(f1c[i]), 3))

resumen = pd.DataFrame(
    [{"entity": c, "f1_mean": round(float(np.mean(v)), 3),
      "n_filas": int((base["entity"] == c).sum()),
      "n_groups": int(base.loc[base["entity"] == c, "group_id"].nunique())}
     for c, v in per_class.items()]
).sort_values("f1_mean")
print(resumen.to_string(index=False))

final = LGBMClassifier(objective="multiclass", num_class=len(clases),
                       class_weight="balanced", num_leaves=15,
                       min_child_samples=5, n_estimators=400,
                       learning_rate=0.05, verbose=-1, random_state=0)
final.fit(Xa, ya, sample_weight=wa)
try:
    from sklearn.frozen import FrozenEstimator as _Frozen
    cal_final = CalibratedClassifierCV(_Frozen(final),
                                       method="sigmoid", cv="prefit")
except ImportError:
    cal_final = CalibratedClassifierCV(final, method="sigmoid", cv="prefit")
cal_final.fit(X, y_lab, sample_weight=w_orig)

folder = dataiku.Folder("fase2_juez_v3")
fdir = folder.get_path()
final.booster_.save_model(os.path.join(fdir, "modelo.txt"))
with open(os.path.join(fdir, "vectorizer.pkl"), "wb") as w:
    pickle.dump(vec, w)
with open(os.path.join(fdir, "clases.json"), "w", encoding="utf-8") as w:
    json.dump(clases, w, ensure_ascii=False)
with open(os.path.join(fdir, "calibrador.pkl"), "wb") as w:
    pickle.dump(cal_final, w)

proba_full = cal_final.predict_proba(X)
conf_full = proba_full.max(axis=1)
pred_full = [clases[i] for i in proba_full.argmax(axis=1)]
_, _, toc = aplicar_fallback(base["light"].tolist(), pred_full,
                             conf_full.tolist(), umbral=UMBRAL_FALLBACK)

debiles = resumen[resumen["f1_mean"] < 0.5]["entity"].tolist()
html = ("<html><head><meta charset='utf-8'><title>Fase 2 v3 — Juez 23 gold_v2</title></head>"
        "<body style='font-family:sans-serif;max-width:1100px;margin:auto'>"
        f"<h1>Juez v3 gold_v2 (clases={len(clases)}, folds={n_splits} por grupo, pesos 1.0/0.5)</h1>"
        f"<p>OOF Accuracy: {np.mean(accs):.3f} | F1 macro OOF: {np.mean(f1s):.3f} "
        f"(previo v2: 0.786 / 0.567 — comparar)</p>"
        f"<p>Eliminadas(&lt;2): {info['eliminadas']}. "
        f"Fallback corrige {toc} train si prob&lt;{UMBRAL_FALLBACK}.</p>"
        f"<p>Debiles (F1&lt;0.5): {debiles}</p>"
        f"{resumen.to_html(index=False)}</body></html>")
with open(os.path.join(fdir, "metricas.html"), "w", encoding="utf-8") as w:
    w.write(html)
print(f"accuracy_OOF={np.mean(accs):.3f} f1_macro_OOF={np.mean(f1s):.3f} clases={len(clases)}")
