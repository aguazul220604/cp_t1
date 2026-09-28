# Dataiku Python recipe: fase2_juez (Modelo Juez LightGBM multiclase)
# Input (Flow):  dataset_validated_entity_v2
# Output (Flow): managed folder fase2_juez (modelo.txt, vectorizer.pkl,
#                clases.json, metricas.html)
# Alcance (.md): SOLO asigna entity/prob_entity. Nunca decide PII.
# Requiere pii_lib/normalize.py con preparar_juez + lightgbm en el code env.
import json
import os
import pickle

import dataiku
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from pii_lib.normalize import preparar_juez
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedKFold

df = dataiku.Dataset("dataset_validated_entity_v2").get_dataframe()
base, fusionadas = preparar_juez(df)

X_txt = base["light"].fillna("").tolist()
y_lab, clases = pd.factorize(base["entity_canon"])
clases = list(clases)

vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
X = vec.fit_transform(X_txt)

n_min = int(pd.Series(y_lab).value_counts().min())
n_splits = max(2, min(5, n_min))
skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=0)

accs, f1s, per_class = [], [], {}
for tr, va in skf.split(X, y_lab):
    clf = LGBMClassifier(objective="multiclass", num_class=len(clases),
                         class_weight="balanced", num_leaves=15,
                         min_child_samples=10, n_estimators=300,
                         learning_rate=0.05, verbose=-1)
    clf.fit(X[tr], y_lab[tr])
    pr = clf.predict(X[va])
    accs.append(accuracy_score(y_lab[va], pr))
    f1s.append(f1_score(y_lab[va], pr, average="macro", zero_division=0))
    f1c = f1_score(y_lab[va], pr, average=None, zero_division=0)
    for i, c in enumerate(clases):
        per_class.setdefault(c, []).append(round(float(f1c[i]), 3))

resumen = pd.DataFrame(
    [{"entity": c, "f1_mean": round(float(np.mean(v)), 3),
      "n": int((base["entity_canon"] == c).sum())} for c, v in per_class.items()]
).sort_values("f1_mean")

final = LGBMClassifier(objective="multiclass", num_class=len(clases),
                       class_weight="balanced", num_leaves=15,
                       min_child_samples=10, n_estimators=300,
                       learning_rate=0.05, verbose=-1)
final.fit(X, y_lab)

folder = dataiku.Folder("fase2_juez")
fdir = folder.get_path()
final.booster_.save_model(os.path.join(fdir, "modelo.txt"))
with open(os.path.join(fdir, "vectorizer.pkl"), "wb") as w:
    pickle.dump(vec, w)
with open(os.path.join(fdir, "clases.json"), "w", encoding="utf-8") as w:
    json.dump(clases, w, ensure_ascii=False)

debiles = resumen[resumen["f1_mean"] < 0.5]["entity"].tolist()
html = ("<html><head><meta charset='utf-8'><title>Fase 2 — Juez</title></head>"
        "<body style='font-family:sans-serif;max-width:1000px;margin:auto'>"
        f"<h1>Fase 2 — Juez (clases={len(clases)}, folds={n_splits})</h1>"
        f"<p>Accuracy: {np.mean(accs):.3f} | F1 macro: {np.mean(f1s):.3f}</p>"
        f"<p>Clases fusionadas a 'otros' (&lt;3 ejemplos): {fusionadas}</p>"
        f"<p>Entidades debiles (F1&lt;0.5, prob_entity esperada baja): {debiles}</p>"
        f"{resumen.to_html(index=False)}</body></html>")
with open(os.path.join(fdir, "metricas.html"), "w", encoding="utf-8") as w:
    w.write(html)
print(f"accuracy={np.mean(accs):.3f} f1_macro={np.mean(f1s):.3f} clases={len(clases)}")
