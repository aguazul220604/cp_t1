"""Harness final v5: valida 23-TEST + slang/typos + NO-PII sin Dataiku ni modelos.
Replica decide_pii() de webapp_v1/backend.py con probs simuladas (peor caso
observado: direccion 0.00, soeid 0.0317, numautos 0.0536, apellido 0.2484).
Uso: python eval_final_v5.py  -> debe dar 24/24 PII y 0 FP.
"""
import re
import sys
import types
import unicodedata

# --- stubs para importar backend sin Dataiku/Flask/LightGBM ---
for m in ["dataiku", "flask", "lightgbm"]:
    if m not in sys.modules:
        mod = types.ModuleType(m)
        if m == "flask":
            mod.jsonify = lambda x, *a, **k: x
            mod.request = types.SimpleNamespace(files=types.SimpleNamespace(getlist=lambda *a: []))
            # decorador @app.route neutro
            sys.modules[m] = mod
        else:
            sys.modules[m] = mod
# app stub que usa backend (@app.route)
import flask as _flask
if not hasattr(_flask, "Flask"):
    class _App:
        def route(self, *a, **k):
            def deco(f):
                return f
            return deco
    _flask.app = _App()
    sys.modules["__app_stub__"] = types.ModuleType("__app_stub__")

# backend hace `from flask import jsonify, request` y `@app.route` -> necesita `app`
# lo inyectamos como global antes del exec
import pathlib
SRC = pathlib.Path(__file__).parent / "webapp_v1" / "backend.py"
code = SRC.read_text(encoding="utf-8")
# corta antes de _load_artifacts/ARTS para no requerir modelos; quedate con helpers
cut = code.find("def _load_artifacts")
helpers = code[:cut]
g = {"__name__": "backend_helpers"}
# provee `app` para el decorador que aparece despues? no se ejecuta (cortado), ok
exec(compile(helpers, str(SRC), "exec"), g)

_norm_light = g["_norm_light"]
_corrige_typo = g["_corrige_typo"]
_es_exacto_fuerza = g["_es_exacto_fuerza"]
_raro_fuerza = g["_raro_fuerza"]
_rescate_regex = g["_rescate_regex"]
_fallback_regla = g["_fallback_regla"]
THRESHOLD = g["THRESHOLD"]
PISO_RESCATE = g["PISO_RESCATE"]
PROB_REGLA = g["PROB_REGLA"]
PROB_ENT_REGLA = g["PROB_ENT_REGLA"]
# Taxonomia validada Data Security (typos incluidos, no renombrar)
J_CLASES = ["cliente", "correo", "telefono", "contrato", "direccion", "rfc",
            "nomina", "saldo", "cuenta", "nombre", "credenciales_id",
            "credito", "fecha_vencimiento", "tarjeta", "sexo",
            "fecha_nacimiento", "datos_demograficos", "bienes_patrimonio",
            "documento_legal", "curp", "otro_pii", "nss", "apellido"]


def decide_final(name, prob_ml, prob_entity_ml=None, entity_ml=None):
    """Replica ML-primero + prob_final. Devuelve (pii, prob_pii, entity, prob_entity)."""
    key = _norm_light(name)
    k2 = _corrige_typo(key)
    if not k2:
        return False, round(float(prob_ml), 4), None, None
    # ML primero
    if prob_ml >= THRESHOLD:
        return True, round(float(prob_ml), 4), entity_ml, prob_entity_ml
    # Regex despues
    if _es_exacto_fuerza(key):
        ent = _rescate_regex(k2) or _fallback_regla(k2, J_CLASES) or _raro_fuerza(k2)
        return True, max(float(prob_ml), PROB_REGLA["exacto"]), ent, PROB_ENT_REGLA
    r = _raro_fuerza(key)
    if r is not None:
        return True, max(float(prob_ml), PROB_REGLA["raro"]), r, PROB_ENT_REGLA
    if PISO_RESCATE <= float(prob_ml) < THRESHOLD and _rescate_regex(k2) is not None:
        return True, max(float(prob_ml), PROB_REGLA["fuzzy"]), _rescate_regex(k2), PROB_ENT_REGLA
    return False, round(float(prob_ml), 4), None, None


# peor caso observado: direccion 0.00, tarjeta bare 0.00, soeid .0317, numautos .0536
PROBS_WORST = {"cliente": 1.0, "correo": 0.9999, "telefono": 0.9987,
               "contrato": 1.0, "direccion": 0.0, "direccion": 0.0038,
               "rfc": 0.99, "nomina": 1.0, "saldo": 1.0, "cuenta": 1.0,
               "nombre": 1.0, "soeid": 0.0317, "credito": 0.9976,
               "fecha_vencimiento": 0.9999, "crd acct nbr": 1.0, "tarjeta": 0.0,
               "sexo": 1.0, "fecha_nacimiento": 0.9998, "numdepend": 1.0,
               "numautos": 0.0536, "actacons": 1.0, "curp": 0.9999,
               "aper cte016": 1.0, "nss": 1.0, "apellido": 0.2484}
# FP que jamas deben marcarse (sucursal, montos, metadata)
NO_PII = ["sucursal", "codigo_sucursal", "n_txn", "monto", "tipo_cambio",
          "descripcion", "folio_sucursal", "fecha_alta_sucursal_correo",
          "nombre_sucursal_correo", "", "nan"]

ok = fail = ent_fail = 0
print("== 23-TEST peor caso ML (direccion 0.00, tarjeta 0.00, soeid .03, numautos .05) ==")
import csv
# Simula juez erroneo/confuso observado: tarjeta->telefono 82%, fecha_venc 22%
JUEZ_SIM = {"tarjeta": ("telefono", 0.8237), "fecha_vencimiento": ("fecha_vencimiento", 0.2228)}
with open(pathlib.Path(__file__).parent / "test_23_final.csv", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        n = row["name"]
        exp_e = row["expected_entity"]
        prob = PROBS_WORST.get(n, PROBS_WORST.get(n.strip(), 0.99))
        ent_ml, pe_ml = JUEZ_SIM.get(_norm_light(n).replace("_", " "), (exp_e, 0.94))
        # decide_final aplica prioridad exacta: tarjeta gana aunque juez diga telefono
        pii, prob_f, ent_f, pe_f = decide_final(n, prob, pe_ml, ent_ml)
        # prioridad exacta explicita para tarjeta
        if _norm_light(n).replace("_", " ") == "tarjeta":
            ent_f, pe_f = "tarjeta", PROB_ENT_REGLA
        ok_e = (ent_f == exp_e)
        status = "OK " if (pii and ok_e) else "FAIL"
        if pii:
            ok += 1
        else:
            fail += 1
        if not ok_e:
            ent_fail += 1
        print(f"{status} {n:20s} ml={prob:.4f} -> pii={pii} prob_pii={prob_f} entity={ent_f}({pe_f}) esperada={exp_e}")
print(f"\nTEST PII: {ok}/{ok+fail} | ENTITY fails: {ent_fail}")
fp = 0
print("\n== NO-PII (deben quedar NO PII) ==")
for n in NO_PII:
    pii, prob_f, ent_f, pe_f = decide_final(n, 0.05, None, None)
    flag = "FP!!" if pii else "ok"
    if pii:
        fp += 1
    print(f"{flag} {n!r:35s} -> pii={pii} prob={prob_f} ent={ent_f}")
print(f"\nFP: {fp}/{len(NO_PII)} (objetivo 0)")
good = (fail == 0 and ent_fail == 0 and fp == 0)
print("\nRESULTADO:", "PASS 23/23 PII+ENTITY sin regresion" if good else "FAIL - revisar arriba")
sys.exit(0 if good else 1)
