# Dataiku Python recipe: fase0_coverage
# Inputs (Flow):  cat_267k_norm, cat_21k_norm
# Outputs (Flow): dataset fase0_cobertura_result + managed folder fase0_html (report.html)
# Requiere pii_lib/normalize.py en Library Editor. Solo libs base: pandas, sklearn, matplotlib.
import io

import base64

import dataiku
import matplotlib
import pandas as pd
from pii_lib.normalize import bucket
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

THRESHOLDS = (80, 85, 90, 95)


def run_variant(cat267, cat21, norm_col):
    q = cat267[cat267["pii_any"]].reset_index(drop=True)
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
    vec.fit(list(cat21[norm_col].fillna("")) + list(q[norm_col].fillna("")))
    X21 = vec.transform(cat21[norm_col].fillna("").tolist())
    Xq = vec.transform(q[norm_col].fillna("").tolist())
    dist, idx = NearestNeighbors(n_neighbors=1, metric="cosine").fit(X21).kneighbors(Xq)
    res = q[["name", "n_rows", "n_true", norm_col]].copy()
    res["vecino_21k"] = cat21.iloc[idx[:, 0]]["name"].values
    res["vecino_pii"] = cat21.iloc[idx[:, 0]]["pii_majority"].values
    res["similarity"] = (1.0 - dist[:, 0]) * 100.0
    res["bucket"] = res["similarity"].map(bucket)
    sens = {t: float((res["similarity"] >= t).mean() * 100) for t in THRESHOLDS}
    return res, sens


def summarize(res):
    by_distinct = res["bucket"].value_counts(normalize=True) * 100
    w = res.groupby("bucket")["n_rows"].sum()
    return {
        "n": len(res),
        "distinct": by_distinct.round(1).to_dict(),
        "rows": (w / w.sum() * 100).round(1).to_dict(),
        "mean": round(float(res["similarity"].mean()), 1),
        "median": round(float(res["similarity"].median()), 1),
    }


def hist_b64(series):
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.hist(series, bins=20)
    ax.set_xlabel("similarity (0-100)")
    ax.set_ylabel("n names")
    ax.set_title("Cobertura: similitud max contra 21k (variante light)")
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


cat267 = dataiku.Dataset("cat_267k_norm").get_dataframe()
cat21 = dataiku.Dataset("cat_21k_norm").get_dataframe()

res_light, sens_light = run_variant(cat267, cat21, "light")
res_aggr, sens_aggr = run_variant(cat267, cat21, "aggr")

dataiku.Dataset("fase0_cobertura_result").write_with_schema(res_light)

s_light, s_aggr = summarize(res_light), summarize(res_aggr)
nula = res_light[res_light["bucket"] == "nula(<50)"].nlargest(20, "n_rows")
parcial = res_light[res_light["bucket"] == "parcial(50-90)"].nlargest(20, "similarity")

html = f"""<html><head><meta charset="utf-8"><title>Fase 0 — Cobertura</title></head>
<body style="font-family:sans-serif;max-width:1000px;margin:auto">
<h1>Fase 0 — Cobertura del 21k sobre PII del 267k</h1>
<h2>Variante light (con digitos, n={s_light["n"]})</h2>
<p>Media/mediana: {s_light["mean"]} / {s_light["median"]} |
Distintos: {s_light["distinct"]} | Ponderado filas: {s_light["rows"]}</p>
<h2>Variante aggr (sin sufijo num, n={s_aggr["n"]})</h2>
<p>Media/mediana: {s_aggr["mean"]} / {s_aggr["median"]} |
Distintos: {s_aggr["distinct"]} | Ponderado filas: {s_aggr["rows"]}</p>
<h2>Sensibilidad umbral fuerte</h2>
<p>light: {sens_light}</p><p>aggr: {sens_aggr}</p>
<img src="data:image/png;base64,{hist_b64(res_light["similarity"])}"/>
<h2>Top cobertura nula (pedir a Data Security)</h2>
{nula[["name", "n_rows", "similarity", "vecino_21k"]].to_html(index=False)}
<h2>Top parcial (revisar 50-90)</h2>
{parcial[["name", "n_rows", "similarity", "vecino_21k"]].to_html(index=False)}
<p><b>Decision:</b> si aggr &gt;&gt; light, el strip de digitos ayuda; si light &gt;&gt; aggr,
los sufijos llevan senal (casa1=TRUE vs casa2=FALSE) y NO deben colapsarse en Fase 3.</p>
</body></html>"""

folder = dataiku.Folder("fase0_html")
with folder.get_writer("report.html") as w:
    w.write(html)
