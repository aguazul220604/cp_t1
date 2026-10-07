# Dataiku Python recipe: conflictos_v3 (familias con etiqueta mixta en el 21k)
# Inputs (Flow): dataset_validated_prepared_labeled_v2 (name, pii, entity)
# Outputs (Flow): dataset f0_conflictos_v3 (name_norm, variantes, n_true,
#                 n_false, entity_true, decision) + managed folder fase1_html
#                 (conflictos.html). Solo diagnostico: la columna decision la
#                 llenas tu (PII / NO_PII / REVISION). Foco: tel casa*, *correo*,
#                 sdo*, cve*, ind*, *crd*, *cust*, *cuenta*, *nomin*, *venc*.
import re
import unicodedata

import dataiku
import pandas as pd

FAMILIAS = [r"\btel\b", r"casa", r"correo", r"\bsdo\b", r"saldo", r"\bcve\b",
            r"nomina", r"ind\b", r"deleg", r"crd", r"cust", r"cuenta",
            r"ordenante", r"venc", r"sucursal"]


def _light(s):
    if pd.isna(s):
        return ""
    s = "".join(c for c in unicodedata.normalize("NFD", str(s).lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def _norm(s):
    return re.sub(r"\s*\d+$", "", _light(s)).strip()


def _is_pii(v):
    if pd.isna(v):
        return False
    if isinstance(v, bool):
        return v
    return str(v).strip().upper() in ("TRUE", "1", "T", "SI")


try:
    df = dataiku.Dataset("dataset_validated_prepared_labeled_v2").get_dataframe()
except Exception:
    df = dataiku.Dataset("dataset_validated_prepared").get_dataframe()

pcol = "pii" if "pii" in df.columns else "target"
df = df[df["name"].notna()].copy()
df["_norm"] = df["name"].map(_norm)
df["_pii"] = df[pcol].map(_is_pii)
df["_ent"] = df["entity"].fillna("").astype(str) if "entity" in df.columns else ""

g = df.groupby("_norm").agg(
    variantes=("name", lambda s: " | ".join(sorted(set(s.astype(str)))[:12])),
    n_true=("_pii", "sum"), n_total=("_pii", "size"),
    entity_true=("_ent", lambda s: " | ".join(sorted(set(x for x in s if x))[:6])),
).reset_index()
g["n_false"] = g["n_total"] - g["n_true"]
mix = g[(g["n_true"] > 0) & (g["n_false"] > 0)].copy()
mix["foco"] = mix["_norm"].apply(
    lambda n: ",".join([f for f in FAMILIAS if re.search(f, n)]) or "otra")
mix = mix.sort_values(["foco", "n_total"], ascending=[True, False])
mix["decision"] = ""  # PII / NO_PII / REVISION (la llenas tu)

dataiku.Dataset("f0_conflictos_v3").write_with_schema(
    mix.rename(columns={"_norm": "name_norm"})
    [["name_norm", "variantes", "n_true", "n_false",
      "entity_true", "foco", "decision"]])

html = ("<html><head><meta charset='utf-8'><title>Conflictos v3</title></head>"
        "<body style='font-family:sans-serif;max-width:1100px;margin:auto'>"
        f"<h1>Familias con etiqueta mixta en el 21k: {len(mix)}</h1>"
        "<p>Llena <b>decision</b> por familia: PII (queda como esta), "
        "NO_PII (se re-etiqueta antes del proximo reentren), "
        "REVISION (banda needs_review en webapp por patron). "
        "Lo genuinamente ambiguo (tel casa1=TRUE vs tel casa ict1=FALSE) "
        "no lo resuelve ningun modelo solo-name: va a banda de revision.</p>"
        f"{mix.head(200).to_html(index=False)}</body></html>")
with dataiku.Folder("fase1_html").get_writer("conflictos.html") as w:
    w.write(html)
print(f"conflictos={len(mix)}")
if len(mix):
    print(mix.head(30).to_string(index=False))
