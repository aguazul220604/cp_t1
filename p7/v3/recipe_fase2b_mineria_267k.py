# Dataiku Python recipe: fase2b_mineria_267k
# REGLA DE ORO: lee SOLO la columna `name` del 267k. Ignora sus etiquetas.
# In (Flow):  dataset_no_validated (o nombre de tu 267k) — se usa solo `name`
# Out (Flow): variantes_lexicas_267k (csvs/dataset con separadores, abreviaturas, calificadores observados)
#             + managed folder o dataset con diccionario JSON de operadores permitidos
#
# Local: python recipe_fase2b_mineria_267k.py --input 267k.csv --output variantes_lexicas_267k.csv --dict operadores.json
import argparse
import json
import re

try:
    import dataiku
    HAS_DATAIKU = True
except ImportError:
    HAS_DATAIKU = False

import pandas as pd

IN_DATASET = "dataset_no_validated"
OUT_DATASET = "variantes_lexicas_267k"
# Managed folder Dataiku donde queda el JSON de operadores permitidos.
# Crealo una vez en el Flow: + New > Folder > nombre `fase2b_lexico` (ID = fase2b_lexico).
OUT_FOLDER = "fase2b_lexico"
OUT_JSON_NAME = "operadores_permitidos.json"

# Familias del doc v2 §Fase 2b — solo estas raices pueden usarse como operador en 2c.
# La mineria confirma cuales SI se observaron en el 267k.
FAMILIAS = {
    "correo": ["correo", "mail", "e-mail", "email", "e_mail"],
    "rfc": ["rfc", "r.f.c.", "idfiscal", "id_fiscal"],
    "sexo": ["sexo", "gndr", "genero"],
    "telefono": ["telefono", "tel", "cel", "phone", "ph", "extn", "ext", "movil"],
    "direccion": ["direccion", "addr", "calle", "colonia", "col", "cp", "edo", "cntry", "country", "city", "estate", "poblacion", "nomcol", "nompob", "zip"],
    "cuenta": ["cuenta", "acct", "acnt", "account", "cta", "ctenum"],
    "tarjeta": ["tarjeta", "card", "crd", "plastico", "nucc"],
    "nomina": ["nomina", "numemp", "numnom", "empleado"],
    "cliente": ["cliente", "clnt", "cust", "ctenum", "gfcid"],
    "nombre": ["nombre", "name", "nom", "apellido", "razon", "beneficiario", "nomcte"],
    "contrato": ["contrato", "contract", "cto"],
    "credito": ["credito", "credit", "loan", "linea", "limite", "lmt", "linnum"],
    "saldo": ["saldo", "sdo", "balance", "bal", "capital"],
    "fecha": ["fecha", "nacim", "nacimiento", "vencim", "expry", "exp", "dt", "fnacim", "fec"],
}
CALIFICADORES = ["titular", "cliente", "beneficiario", "subc", "ordenante", "suborigen", "origen"]


def detectar_separadores(names: pd.Series) -> dict:
    s = names.fillna("").astype(str)
    n = max(len(s), 1)
    return {
        "underscore": float(s.str.contains("_").mean()),
        "guion": float(s.str.contains("-").mean()),
        "espacio": float(s.str.contains(" ").mean()),
        "punto": float(s.str.contains(r"\.").mean()),
        "sin_sep": float((~s.str.contains(r"[_\- .]")).mean()),
        "camel": float(s.str.contains(r"[a-z][A-Z]").mean()),
        "mayusculas_full": float(s.str.contains(r"^[A-Z0-9 _\-/\.]+$").fillna(False).mean()),
        "n": int(len(s)),
    }


def minar_familias(names: pd.Series) -> pd.DataFrame:
    low = names.fillna("").astype(str).str.lower()
    rows = []
    for fam, variantes in FAMILIAS.items():
        for v in variantes:
            pat = re.escape(v.lower())
            cnt = int(low.str.contains(pat, regex=True).sum())
            if cnt > 0:
                rows.append({"familia": fam, "variante": v, "n_obs": cnt})
    if not rows:
        return pd.DataFrame(columns=["familia", "variante", "n_obs"])
    return pd.DataFrame(rows).sort_values(["familia", "n_obs"], ascending=[True, False]).reset_index(drop=True)


def minar_calificadores(names: pd.Series) -> pd.DataFrame:
    low = names.fillna("").astype(str).str.lower()
    rows = []
    for c in CALIFICADORES:
        cnt = int(low.str.contains(re.escape(c)).sum())
        if cnt > 0:
            rows.append({"calificador": c, "n_obs": cnt})
    if not rows:
        return pd.DataFrame(columns=["calificador", "n_obs"])
    return pd.DataFrame(rows).sort_values("n_obs", ascending=False).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="267k.csv")
    ap.add_argument("--output", default="variantes_lexicas_267k.csv")
    ap.add_argument("--dict", default="operadores.json", dest="dict_path")
    a = ap.parse_args()

    if HAS_DATAIKU:
        try:
            df = dataiku.Dataset(IN_DATASET).get_dataframe()
            # SOLO texto: ignora cualquier label aunque exista
            names = df["name"] if "name" in df.columns else df.iloc[:, 0]
            sep = detectar_separadores(names)
            fam = minar_familias(names)
            cal = minar_calificadores(names)
            # Dataset salida: una tabla larga de evidencia observada
            fam_out = fam.rename(columns={"familia": "tipo", "variante": "valor"})
            cal_out = cal.rename(columns={"calificador": "valor"}).assign(tipo="calificador")
            sep_out = pd.DataFrame([{"tipo": "separador", "valor": k, "n_obs": round(v * len(names)) if k != "n" else v}
                                    for k, v in sep.items() if k != "n"])
            out = pd.concat([fam_out, cal_out, sep_out], ignore_index=True)
            dataiku.Dataset(OUT_DATASET).write_with_schema(out)
            # JSON de operadores -> managed folder (misma recipe, segundo output).
            # En el Flow: selecciona la recipe > Settings > Outputs > + Add > Folder `fase2b_lexico`.
            payload = {"separadores": sep, "familias_observadas": fam.to_dict("records"),
                       "calificadores_observados": cal.to_dict("records")}
            try:
                folder = dataiku.Folder(OUT_FOLDER)
                with folder.get_writer(OUT_JSON_NAME) as w:
                    w.write(json.dumps(payload, ensure_ascii=False, indent=2))
                print(f"JSON escrito en folder '{OUT_FOLDER}/{OUT_JSON_NAME}'")
            except Exception as fe:
                # Si el folder aun no esta enlazado como output, no tumbar la recipe:
                # imprime el JSON para pegarlo manual en el folder.
                print(f"AVISO: no se pudo escribir en folder '{OUT_FOLDER}' ({fe}). "
                      f"Crea el managed folder y enlazalo como output, o guarda manual este JSON "
                      f"como '{OUT_JSON_NAME}':\n{json.dumps(payload, ensure_ascii=False, indent=2)}")
            print(f"OK 2b: {len(names)} names, {len(fam)} variantes familia, "
                  f"{len(cal)} calificadores, seps={ {k: round(v,3) for k,v in sep.items() if k!='n'} }")
            print("SOLO se observaron las variantes listadas: cualquier operador de 2c fuera de esta lista esta PROHIBIDO.")
            return
        except Exception as e:
            print(f"Dataiku no disponible ({e}), modo local.")

    df = pd.read_csv(a.input)
    names = df["name"] if "name" in df.columns else df.iloc[:, 0]
    sep = detectar_separadores(names)
    fam = minar_familias(names)
    cal = minar_calificadores(names)
    fam_out = fam.rename(columns={"familia": "tipo", "variante": "valor"})
    cal_out = cal.rename(columns={"calificador": "valor"}).assign(tipo="calificador")
    sep_out = pd.DataFrame([{"tipo": "separador", "valor": k, "n_obs": round(v * len(names)) if k != "n" else v}
                            for k, v in sep.items() if k != "n"])
    out = pd.concat([fam_out, cal_out, sep_out], ignore_index=True)
    out.to_csv(a.output, index=False)
    with open(a.dict_path, "w", encoding="utf-8") as f:
        json.dump({"separadores": sep, "familias_observadas": fam.to_dict("records"),
                   "calificadores_observados": cal.to_dict("records")}, f, ensure_ascii=False, indent=2)
    print(f"OK 2b local: -> {a.output}, {a.dict_path}")


if __name__ == "__main__":
    main()
