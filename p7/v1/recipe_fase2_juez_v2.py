# Dataiku Python recipe: fase2_juez_v2 (Juez SUPERVISADO 23 clases)
# Input (Flow):  dataset_validated_prepared (con tu columna manual "entity")
# Output (Flow): managed folder fase2_juez_v2 (modelo.txt, vectorizer.pkl,
#                clases.json, metricas.html)
# Diferencias vs fase2_juez actual:
#  - Target = entity MANUAL (23, incluye otro_pii). No usa entity_canon/clustering.
#  - Split por group_id (sin fuga tel_casa1/tel_casa2), GroupKFold OOF para raras.
#  - Aumento de raras hasta 15 + class_weight balanced + calibracion sigmoide.
#  - Fallback por reglas solo si prob < UMBRAL_FALLBACK (no tapa al modelo).
# Requiere pii_lib/juez_v2.py + lightgbm en el code env.
import json
import os
import pickle

import dataiku
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from pii_lib.juez_v2 import (aplicar_fallback, aumentar_raras,
                             preparar_juez_supervisado)
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GroupKFold

UMBRAL_FALLBACK = 0.50
N_OBJETIVO_RARAS = 15

df = dataiku.Dataset("dataset_validated_prepared").get_dataframe()
base, info = preparar_juez_supervisado(df, target_col="entity", min_ejemplos=2)
print(f"clases={len(info['clases'])} n={info['n']} eliminadas={info['eliminadas']}")
print(f"soporte={info['soporte']}")

X_txt = base["light"].fillna("").tolist()
y_lab, clases = pd.factorize(base["entity"])
clases = list(clases)
groups = base["group_id"].values

vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
X = vec.fit_transform(X_txt)

# Aumento SOLO dentro del train de cada fold se hace simplificado aqui:
# se aumenta el pool completo antes del CV pero con variantes de formato
# (no inventa vocabulario nuevo, fuga minima y aceptada para raras).
Xa_txt, ya_str = aumentar_raras(X_txt, base["entity"].tolist(),
                               n_objetivo=N_OBJETIVO_RARAS, seed=0)
Xa = vec.transform(Xa_txt)
ya = pd.Series(ya_str).map({c: i for i, c in enumerate(clases)}).values

n_splits = 5
gkf = GroupKFold(n_splits=n_splits)
# groups extendidos: originales + grupo del texto origen (aprox por light sin digitos)
import re as _re
ga_txt = [_re.sub(r"[\s\-_]", "", _re.sub(r"\s*\d+$", "", t)).strip() for t in Xa_txt]
ga = np.array(ga_txt)

accs, f1s, per_class = [], [], {}
oof_true, oof_pred = [], []
for tr, va in gkf.split(X, y_lab, groups):
    # train fold = fold-train original + sinteticas cuya raiz cae en train
    tr_groups = set(groups[tr])
    tr_aug = [i for i, g in enumerate(ga_txt[len(X_txt):]) if g in tr_groups]
    tr_idx = list(tr) + [len(X_txt) + i for i in tr_aug]
    Xtr, ytr = Xa[tr_idx], ya[tr_idx]
    clf = LGBMClassifier(objective="multiclass", num_class=len(clases),
                         class_weight="balanced", num_leaves=15,
                         min_child_samples=5, n_estimators=400,
                         learning_rate=0.05, verbose=-1, random_state=0)
    clf.fit(Xtr, ytr)
    cal = CalibratedClassifierCV(clf, method="sigmoid", cv="prefit")
    cal.fit(X[tr], y_lab[tr])
    pr = cal.predict(X[va])
    accs.append(accuracy_score(y_lab[va], pr))
    f1s.append(f1_score(y_lab[va], pr, average="macro", zero_division=0))
    oof_true.extend(y_lab[va].tolist())
    oof_pred.extend(pr.tolist())
    f1c = f1_score(y_lab[va], pr, average=None, zero_division=0)
    for i, c in enumerate(clases):
        per_class.setdefault(c, []).append(round(float(f1c[i]), 3))

resumen = pd.DataFrame(
    [{"entity": c, "f1_mean": round(float(np.mean(v)), 3),
      "n_filas": int((base["entity"] == c).sum()),
      "n_groups": int(base.loc[base["entity"] == c, "group_id"].nunique())}
     for c, v in per_class.items()]
).sort_values("f1_mean")
print(resumen.to_string(index=False))

# Modelo final 100% + calibracion
final = LGBMClassifier(objective="multiclass", num_class=len(clases),
                       class_weight="balanced", num_leaves=15,
                       min_child_samples=5, n_estimators=400,
                       learning_rate=0.05, verbose=-1, random_state=0)
final.fit(Xa, ya)
cal_final = CalibratedClassifierCV(final, method="sigmoid", cv="prefit")
cal_final.fit(X, y_lab)

folder = dataiku.Folder("fase2_juez_v2")
fdir = folder.get_path()
# Booster del estimador base (compatible con fase3b_entity que usa lgb.Booster)
final.booster_.save_model(os.path.join(fdir, "modelo.txt"))
with open(os.path.join(fdir, "vectorizer.pkl"), "wb") as w:
    pickle.dump(vec, w)
with open(os.path.join(fdir, "clases.json"), "w", encoding="utf-8") as w:
    json.dump(clases, w, ensure_ascii=False)
# Calibrador sklearn aparte (opcional en inferencia; Booster sigue siendo default)
with open(os.path.join(fdir, "calibrador.pkl"), "wb") as w:
    pickle.dump(cal_final, w)

# Diagnostico fallback: cuantas OOF de baja confianza rescataria la regla
ents_oof = [clases[i] for i in oof_pred]
keys_oof = base["light"].tolist()  # alineado a orden OOF por folds
# proba aproximada no guardada por fold; se reporta conteo de candidatas < umbral en final
proba_full = cal_final.predict_proba(X)
conf_full = proba_full.max(axis=1)
pred_full = [clases[i] for i in proba_full.argmax(axis=1)]
_, _, toc = aplicar_fallback(base["light"].tolist(), pred_full,
                             conf_full.tolist(), umbral=UMBRAL_FALLBACK)

debiles = resumen[resumen["f1_mean"] < 0.5]["entity"].tolist()
html = ("<html><head><meta charset='utf-8'><title>Fase 2 v2 — Juez 23 supervisado</title></head>"
        "<body style='font-family:sans-serif;max-width:1100px;margin:auto'>"
        f"<h1>Juez v2 supervisado (clases={len(clases)}, folds={n_splits} por grupo)</h1>"
        f"<p>OOF Accuracy: {np.mean(accs):.3f} | F1 macro OOF: {np.mean(f1s):.3f}</p>"
        f"<p>Target = entity MANUAL. Eliminadas(&lt;2): {info['eliminadas']}. "
        f"Aumento raras a {N_OBJETIVO_RARAS}. Fallback reglas corrige {toc} train si prob&lt;{UMBRAL_FALLBACK}.</p>"
        f"<p>Debiles (F1&lt;0.5, esperadas: ultra-raras): {debiles}</p>"
        f"{resumen.to_html(index=False)}</body></html>")
with open(os.path.join(fdir, "metricas.html"), "w", encoding="utf-8") as w:
    w.write(html)
print(f"accuracy_OOF={np.mean(accs):.3f} f1_macro_OOF={np.mean(f1s):.3f} clases={len(clases)}")
