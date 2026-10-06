# Dataiku Python recipe: faseA_auditoria_manual_vs_canon
# Inputs (Flow): dataset_validated_prepared (con tu columna manual "entity"),
#                dataset_validated_entity_v2 (con entity_canon del clustering)
# Outputs (Flow): dataset auditoria_entity + managed folder fase1_html (auditoria.html)
# Objetivo: cuantificar por que el Juez actual solo ve ~14 y tus 23 se colapsan.
# Solo lectura + reporte. No reentrena nada.
import dataiku
import pandas as pd
from sklearn.metrics import homogeneity_completeness_v_measure

man = dataiku.Dataset("dataset_validated_prepared").get_dataframe()
can = dataiku.Dataset("dataset_validated_entity_v2").get_dataframe()

# Normalizacion minima v3 para group_id (sin ROOTS): lower, sin acentos, strip num final
import re
import unicodedata


def _light(s):
    if pd.isna(s):
        return ""
    s = "".join(c for c in unicodedata.normalize("NFD", str(s).lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def _norm(s):
    return re.sub(r"\s*\d+$", "", _light(s)).strip()


def _gid(s):
    return re.sub(r"[\s\-_]", "", _norm(s))


man["light"] = man["name"].map(_light)
man["name_norm"] = man["name"].map(_norm)
man["group_id"] = man["name"].map(_gid)

# Solo filas PII con entity manual (deberian ser ~943 segun tus imgs)
pii_col = "pii" if "pii" in man.columns else "target"
is_pii = man[pii_col].astype(str).str.upper().isin(["TRUE", "1", "T", "SI", "1.0"]) \
    if man[pii_col].dtype == object else man[pii_col].astype(bool)
mp = man[is_pii & man["entity"].notna()].copy()
print(f"manuales PII con entity: {len(mp)} | distintas: {mp['entity'].nunique()}")
print(mp["entity"].value_counts().to_string())

# Cruce con canon por name (left join)
cols_can = [c for c in ["name", "Entity", "entity_canon", "cluster"] if c in can.columns]
merged = mp.merge(can[cols_can].drop_duplicates("name"), on="name", how="left")

# 1) Soporte por group_id (lo que realmente importa para CV)
g = merged.groupby("entity").agg(n_filas=("entity", "size"),
                                 n_names=("name", "nunique"),
                                 n_groups=("group_id", "nunique"))
g["riesgo"] = g["n_groups"].map(lambda n: "CRITICO(<5)" if n < 5
                                else ("BAJO(5-10)" if n <= 10 else "ok"))
print("\nSoporte por group_id:\n" + g.sort_values("n_filas", ascending=False).to_string())

# 2) Matriz manual(23) x canon(~14): aqui se ve el colapso
ct = pd.crosstab(merged["entity"], merged["entity_canon"].fillna("(sin_canon)"))
print("\nCrosstab manual x canon:\n" + ct.to_string())

# 3) Pureza del clustering respecto a tu etiquetado
mask = merged["entity_canon"].notna()
if mask.sum() > 0:
    h, c, v = homogeneity_completeness_v_measure(
        merged.loc[mask, "entity"].astype(str),
        merged.loc[mask, "entity_canon"].astype(str))
    print(f"\nhomogeneidad={h:.3f} completitud={c:.3f} V={v:.3f}")
    print("h alta + c baja = clustering fragmenta; h baja = clustering mezcla tus 23.")

# 4) Canon no cubiertas: entidades manuales que caen >80% a 'otros'/una sola canon
resumen = []
for ent, grp in merged.groupby("entity"):
    top = grp["entity_canon"].fillna("(sin_canon)").value_counts(normalize=True)
    resumen.append({"entity": ent, "n": len(grp),
                    "canon_top": top.index[0], "pct_top": round(float(top.iloc[0]) * 100, 1)})
resumen = pd.DataFrame(resumen).sort_values("n", ascending=False)

dataiku.Dataset("auditoria_entity").write_with_schema(
    merged[["name", "name_norm", "group_id", "entity", "entity_canon", "Entity"]])

html = ("<html><head><meta charset='utf-8'><title>Auditoria entity manual vs canon</title></head>"
        "<body style='font-family:sans-serif;max-width:1100px;margin:auto'>"
        "<h1>Fase A — Manual (23) vs Canon clustering (~14)</h1>"
        f"<p>Filas PII con entity manual: {len(mp)}. "
        f"Homogeneidad={h:.3f} Completitud={c:.3f} V={v:.3f} (si aplica).</p>"
        f"<h2>Soporte por group_id</h2>{g.sort_values('n_filas', ascending=False).to_html()}"
        f"<h2>Destino canon por entidad manual</h2>{resumen.to_html(index=False)}"
        f"<h2>Crosstab completo</h2>{ct.to_html()}"
        "<p>Lectura: si varias de tus 23 caen a la misma canon "
        "(ej. rfc/curp/nss→id_persona, nombre/apellido→nombre_persona), "
        "el Juez-14 nunca podra predecirlas. Hay que reentrenar supervisado (Fase 2 v2).</p>"
        "</body></html>")
with dataiku.Folder("fase1_html").get_writer("auditoria.html") as w:
    w.write(html)
