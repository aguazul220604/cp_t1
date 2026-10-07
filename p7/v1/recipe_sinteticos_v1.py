# Dataiku Python recipe: sinteticos_v1 (lexico ES/EN + derivados, mundo cerrado)
# Input (Flow):  gold_v2 (name, entity) [+ gold_match90_import si ya existe]
# Output (Flow): dataset gold_sintetico (name, entity, label_source, w)
# LEXICO_V1 locked con usuario: edad->fecha_nacimiento; `ap` suelto prohibido;
# fecha_nacimiento con anti-filtro venc. label_source=sintetico, w=0.3,
# tope ≤30% del PII base. Solo de semillas autorizadas (misma entidad).
import re
import unicodedata

import dataiku
import numpy as np
import pandas as pd

W_SINTETICO = 0.3
N_OBJETIVO = 15
TOPE_FRACCION = 0.30
MODS = ["", "1", "2", " cliente", " cte", "_1", "_2"]

# termino -> se genera tal cual x formatos (bare, pegado, guion_bajo, +dijito)
LEXICO_V1_FINAL = LEXICO_V1 = {
    # FINAL v5: se agregan slang 267k + raras perdidas (numautos, car dlr,
    # soeid ya estaba, addr, crd/acct). Sin esto el binario pierde soeid/numautos.
    "direccion": ["direccion", "address", "addr", "addr_line_1", "colonia",
                  "municipio", "alcaldia", "entidad_federativa",
                  "codigo_postal", "calle", "numero_exterior",
                  "numero_interior", "poblacion", "nomcol", "cntry", "city"],
    "correo": ["correo", "email", "mail", "correo_personal", "correo_trabajo"],
    "fecha_nacimiento": ["fecha_nacimiento", "nacim", "fnac", "fnacim",
                         "birth_date", "dob", "dia_nacimiento",
                         "mes_nacimiento", "anio_nacimiento", "edad"],
    "apellido": ["apellido", "ap_paterno", "ap_materno", "paterno", "materno",
                 "primer_apellido", "segundo_apellido", "surname", "last_name"],
    "telefono": ["telefono", "tel", "cel", "phone", "telefono_casa",
                 "telefono_oficina", "telefono_movil", "extension"],
    "cliente": ["cliente", "cust", "customer", "client", "num_cliente",
                "id_cliente", "borrower"],
    "cuenta": ["cuenta", "cta", "acct", "acct_nbr", "account", "num_cuenta",
               "cuenta_cheques", "cuenta_eje"],
    "tarjeta": ["tarjeta", "plastico", "card", "crd", "crd_acct_nbr",
                "num_tarjeta", "tarjeta_credito", "tarjeta_debito"],
    "contrato": ["contrato", "contract", "num_contrato", "contrato_credito"],
    "credito": ["credito", "credit", "loan", "num_credito", "monto_credito",
                "plazo_credito"],
    "saldo": ["saldo", "sdo", "balance", "saldo_promedio", "saldo_actual",
              "saldo_vencido"],
    "nomina": ["nomina", "payroll", "nomina_semanal", "patron", "num_empleado"],
    "rfc": ["rfc", "tax_id", "rfc_cliente", "rfc_empresa"],
    "curp": ["curp", "curp_trabajador"],
    "nss": ["nss", "imss", "seguro_social", "ssn", "num_afiliacion",
            "derechohabiente"],
    "nombre": ["nombre", "nom", "name", "first_name", "primer_nombre",
               "segundo_nombre", "nombre_cliente", "razon_social"],
    "sexo": ["sexo", "genero", "gender"],
    "datos_demograficos": ["estado_civil", "nacionalidad", "ocupacion",
                           "escolaridad", "dependientes", "numdepend",
                           "num_dependientes"],
    "documento_legal": ["acta", "actacons", "escritura", "poder_notarial",
                        "notaria", "amparo", "demanda", "ine", "pasaporte",
                        "licencia", "cedula_prof", "cartilla", "creactecto"],
    "credenciales_id": ["password", "token", "login", "auth", "soeid", "geid",
                        "firma_electronica", "efirma", "api_key"],
    "bienes_patrimonio": ["inmueble", "patrimonio", "hipoteca", "avaluo",
                          "predial", "vehiculo", "propiedad", "garantia",
                          "colateral", "numautos", "num_autos", "car_dlr",
                          "car_dlrn"],
    "otro_pii_canonical": [],  # placeholder: aper cte016 va a otro_pii solo via match90/pool, no sintetico
    "fecha_vencimiento": ["fecha_vencimiento", "vencimiento", "vigencia",
                          "expiry", "fecha_venc_tarjeta", "fecha_expiracion"],
    # otro_pii: sin lexico (solo cuarentena, no se sintetiza)
}


def _light(s):
    if pd.isna(s):
        return ""
    s = "".join(c for c in unicodedata.normalize("NFD", str(s).lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def _variantes(term, rng):
    t = term.replace("_", " ")
    cands = [t, t.replace(" ", ""), t.replace(" ", "_"),
             f"{t} {rng.randint(1, 9)}", f"{t}{rng.randint(1, 99)}"]
    for m in MODS:
        if m and len(cands) < 8:
            cands.append((t + m).strip())
    return cands


base = dataiku.Dataset("gold_v2").get_dataframe()
try:
    imp = dataiku.Dataset("gold_match90_import").get_dataframe()
    base = pd.concat([base[["name", "entity"]], imp[["name", "entity"]]],
                     ignore_index=True)
except Exception as e:
    print(f"sin match90 (solo gold_v2): {e}")

base["entity"] = base["entity"].astype(str).str.strip().str.lower()
exist = {_light(n) for n in base["name"].dropna().astype(str)}
rng = np.random.RandomState(0)
tope_total = int(len(base) * TOPE_FRACCION)

rows = []
counts = base["entity"].value_counts()
for ent, terms in LEXICO_V1.items():
    n_have = int(counts.get(ent, 0))
    need = max(0, N_OBJETIVO - n_have)
    made = 0
    for term in terms:
        if made >= need or len(rows) >= tope_total:
            break
        for v in _variantes(term, rng):
            if made >= need or len(rows) >= tope_total:
                break
            if _light(v) in exist or not _light(v):
                continue
            # fecha_nacimiento: anti-filtro venc (mundo cerrado)
            if ent == "fecha_nacimiento" and any(
                    a in _light(v) for a in ["venc", "expira", "expiry", "vigencia"]):
                continue
            rows.append({"name": v.strip(), "entity": ent,
                         "label_source": "sintetico", "w": W_SINTETICO})
            exist.add(_light(v))
            made += 1

out = pd.DataFrame(rows, columns=["name", "entity", "label_source", "w"])
dataiku.Dataset("gold_sintetico").write_with_schema(out)
print(f"sinteticos={len(out)} (tope {tope_total}, base PII={len(base)})")
if len(out):
    print(out.groupby("entity").size().to_string())
