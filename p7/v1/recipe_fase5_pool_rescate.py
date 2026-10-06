# Dataiku Python recipe: fase5_pool_rescate (ronda 1 - 7 debiles Juez v2)
# Inputs (Flow): dataset_no_validated_prepared (pool 267k con description/type),
#                dataset_validated_prepared_labeled_v2 (gold, para excluir lo ya visto)
#                dataset_267k_pii_entity_v2 (opcional: para priorizar prob_entity<0.5 -> otro_pii)
# Outputs (Flow): dataset pool_labeling_round_1 (candidatos a etiquetar)
#                 + managed folder fase5_html (rescate.html para revision)
# Objetivo: pasar nss/bienes/documento/etc de 2-7 filas a 15+ grupos reales.
# No entrena nada. Genera plantilla lista para Editable Dataset.
import re
import unicodedata

import dataiku
import pandas as pd

# Keywords por entidad debil (F1=0 en tu metricas.html) + frontera fecha_nacimiento.
# Mantener minusculas, sin acentos. Ajusta a tu criterio de negocio.
KEYWORDS = {
    "apellido": ["apellido", "ap_paterno", "ap_materno", "paterno", "materno",
                 "surname", "last_name", "mothers_last", "fathers_last"],
    "fecha_nacimiento": ["nacim", "fnac", "fnacim", "f_nac", "birth", "dob",
                         "fecha_nac", "fechanac"],
    "nss": ["nss", "seguro_social", "num_seguro", "imss", "nssocial"],
    "documento_legal": ["acta", "poder_notarial", "escritura", "notaria",
                        "amparo", "demanda", "ine", "ife", "pasaporte",
                        "licencia", "cedula_prof", "cartilla"],
    "credenciales_id": ["password", "passwd", "pwd", "token", "auth",
                        "login", "credencial", "firma_elec", "efirma",
                        "private_key", "api_key", "secret"],
    "datos_demograficos": ["edad", "estado_civil", "ecivil", "nacionalidad",
                           "demograf", "marginacion", "ocupacion",
                           "escolaridad", "religion"],
    "bienes_patrimonio": ["inmueble", "bien", "patrimonio", "propiedad",
                          "vehiculo", "hipoteca", "avaluo", "predial",
                          "escritura_bien"],
}
# Frontera explicita: evita que fecha_vencimiento caiga aqui
ANTI = {"fecha_nacimiento": ["venc", "expira", "expiry", "vigencia"]}

TOP_N_POR_ENTIDAD = 60  # tope para que la ronda sea etiquetable (7x60=420 max)


def _light(s):
    if pd.isna(s):
        return ""
    s = "".join(c for c in unicodedata.normalize("NFD", str(s).lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


pool = dataiku.Dataset("dataset_no_validated_prepared").get_dataframe()
try:
    gold = dataiku.Dataset("dataset_validated_prepared_labeled_v2").get_dataframe()
except Exception:
    gold = dataiku.Dataset("dataset_validated_prepared").get_dataframe()

gold_names = set(gold["name"].dropna().astype(str).str.strip())
gold_light = {_light(n) for n in gold_names}

# Deduplica pool por name: n_filas, datasets, type y description de ejemplo
pool["name"] = pool["name"].astype(str).str.strip()
pool = pool[~pool["name"].isin(gold_names)].copy()
pool["_light"] = pool["name"].map(_light)
pool = pool[~pool["_light"].isin(gold_light)].copy()

g = pool.groupby("name", as_index=False).agg(
    n_filas=("name", "size"),
    datasets=("dataset", lambda s: " | ".join(sorted(set(s.astype(str)))[:5])),
    tipos=("type", lambda s: " | ".join(sorted(set(s.fillna("").astype(str)))[:5])),
    desc_ejemplo=("description", lambda s: next(
        (str(x)[:300] for x in s if str(x).strip() not in ("", "nan", "None")), "")),
)
g["_light"] = g["name"].map(_light)
g["_flat"] = (" " + g["_light"].str.replace("_", " ", regex=False) + " ")


def match_kw(flat, kws):
    hits = [k for k in kws if k in flat]
    return hits


rows = []
for ent, kws in KEYWORDS.items():
    anti = ANTI.get(ent, [])
    m = g[g["_flat"].apply(lambda f: any(k in f for k in kws)
                           and not any(a in f for a in anti))].copy()
    m["entity_sugerida"] = ent
    m["motivo"] = m["_flat"].apply(lambda f: ",".join(match_kw(f, kws)))
    # Prioriza: mas filas primero, luego match mas especifico (keyword larga)
    m["_score"] = m["n_filas"] * 10 + m["motivo"].str.len()
    m = m.sort_values("_score", ascending=False).head(TOP_N_POR_ENTIDAD)
    rows.append(m)
    print(f"{ent}: {len(m)} candidatos")

# Baja confianza del Juez actual -> candidatos a otro_pii (si existe el dataset v2)
try:
    v2 = dataiku.Dataset("dataset_267k_pii_entity_v2").get_dataframe()
    low = v2[v2["prob_entity"].fillna(1.0) < 0.5].copy()
    low = low[~low["name"].astype(str).str.strip().isin(gold_names)]
    ln = low.groupby("name", as_index=False).agg(
        n_filas=("name", "size"),
        prob_min=("prob_entity", "min"),
        pred_top=("entity", lambda s: s.value_counts().index[0]
                  if len(s) else ""))
    ln = ln.sort_values("prob_min").head(TOP_N_POR_ENTIDAD)
    ln["_light"] = ln["name"].map(_light)
    ln["_flat"] = " " + ln["_light"].str.replace("_", " ", regex=False) + " "
    ln["entity_sugerida"] = "otro_pii"
    ln["motivo"] = "prob_entity<0.5 pred=" + ln["pred_top"].astype(str)
    ln["datasets"] = ""
    ln["tipos"] = ""
    ln["desc_ejemplo"] = ""
    rows.append(ln[[c for c in ["name", "n_filas", "datasets", "tipos",
                               "desc_ejemplo", "_light", "_flat",
                               "entity_sugerida", "motivo"]]])
    print(f"otro_pii (baja confianza): {len(ln)} candidatos")
except Exception as e:
    print(f"sin v2 para otro_pii: {e}")

out = pd.concat(rows, ignore_index=True).drop_duplicates("name")
# Columnas finales = plantilla de etiquetado (lista para Editable Dataset)
out["entity"] = ""  # columna a llenar por el etiquetador
out["notas"] = ""
out = out[["entity_sugerida", "name", "n_filas", "datasets", "tipos",
           "desc_ejemplo", "motivo", "entity", "notas"]].sort_values(
    ["entity_sugerida", "n_filas"], ascending=[True, False])

dataiku.Dataset("pool_labeling_round_1").write_with_schema(out)

rep = out.groupby("entity_sugerida").agg(
    n_nombres=("name", "nunique"),
    n_filas=("n_filas", "sum")).reset_index().sort_values("n_nombres")
html = ("<html><head><meta charset='utf-8'><title>Ronda 1 — Rescate pool</title></head>"
        "<body style='font-family:sans-serif;max-width:1100px;margin:auto'>"
        "<h1>Ronda 1 — Candidatos pool para las 7 debiles (F1=0)</h1>"
        f"<p>Total candidatos: {len(out)} nombres distintos. "
        "Etiqueta la columna <b>entity</b> (solo esos), deja vacio = no PII / dudoso. "
        "Luego se anexan a gold_v2 con <b>label_source=manual_pool</b> y peso 0.5, "
        "y se re-entrena el Juez v2. Hold-out validado no se toca.</p>"
        f"{rep.to_html(index=False)}"
        f"{out.head(100).to_html(index=False)}"
        "<p>Tip: usa <b>description/tipos/datasets</b> solo como contexto visual "
        "(no seran features). Prioriza apellido vs nombre y nacim vs venc.</p>"
        "</body></html>")
with dataiku.Folder("fase5_html").get_writer("rescate.html") as w:
    w.write(html)
print(f"candidatos={len(out)}")
print(rep.to_string(index=False))
