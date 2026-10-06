# Dataiku Python recipe: pool_labeling_prepare_v1 (fallback null versionado)
# Input (Flow):  pool_labeling_round_1 (entity_sugerida, name, n_filas, ...)
# Output (Flow): dataset pool_labeling_round_1_labeled
# Replica la formula Prepare corregida en Python para que sea auditable y
# re-ejecutable. Fallback = null (""), NUNCA otro_pii en bloque.
# Orden especifico->general, lowercase siempre, anti-filtro venc.
import re
import unicodedata

import dataiku
import pandas as pd

REGLAS = [
    ("nss", [r"nss", r"seguridad_imss", r"seg_social", r"imss"], []),
    ("fecha_nacimiento",
     [r"fnac", r"fnacim", r"nacim", r"birth", r"\bdob\b",
      r"fecha_nac", r"fechanac"], [r"venc", r"expira", r"expiry", r"vigencia"]),
    ("apellido",
     [r"apellido", r"ap_paterno", r"ap_materno", r"paterno", r"materno",
      r"surname", r"last_name"], []),
    ("documento_legal",
     [r"acta", r"poder_notarial", r"escritura", r"notaria", r"amparo",
      r"demanda", r"pasaporte", r"licencia", r"cedula_prof", r"cartilla",
      r"creactecto", r"actacons"], []),
    ("credenciales_id",
     [r"soeid", r"geid", r"password", r"passwd", r"pwd", r"token", r"auth",
      r"login", r"credencial", r"firma_elec", r"efirma", r"tok_req",
      r"dispositivo", r"medio_acceso"], []),
    ("datos_demograficos",
     [r"numdepend", r"dependientes", r"ocupacion", r"ptrmadre",
      r"indicador_extranjero", r"estado_civil", r"ecivil", r"nacionalidad",
      r"demograf", r"marginacion", r"escolaridad"], []),
    ("bienes_patrimonio",
     [r"inmueble", r"patrimonio", r"hipoteca", r"avaluo", r"predial",
      r"vehiculo", r"propiedad"], []),
]


def _light(s):
    if pd.isna(s):
        return ""
    s = "".join(c for c in unicodedata.normalize("NFD", str(s).lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def etiquetar(nombre):
    flat = " " + _light(nombre).replace("_", " ") + " "
    for ent, pos, anti in REGLAS:
        if anti and any(re.search(a, flat) for a in anti):
            continue
        if any(re.search(p, flat) for p in pos):
            # fecha_nacimiento exige pasar el anti-filtro; resto directo
            if ent == "fecha_nacimiento" and any(
                    a in flat for a in ["venc", "expira", "expiry", "vigencia"]):
                continue
            return ent, ",".join([p for p in pos if re.search(p, flat)])
    return "", ""  # fallback null: no entra a gold


df = dataiku.Dataset("pool_labeling_round_1").get_dataframe()
ents, motivos = zip(*df["name"].map(etiquetar))
df["entity"] = list(ents)
df["motivo_regex"] = list(motivos)
df["notas"] = "regex_v1_null_" + df["entity_sugerida"].fillna("").astype(str)

dataiku.Dataset("pool_labeling_round_1_labeled").write_with_schema(df)

rep = df.groupby("entity").size().reset_index(name="n_nombres")
print(rep.to_string(index=False))
print(f"nulas (revision manual/descartar): {(df['entity'] == '').sum()} de {len(df)}")
