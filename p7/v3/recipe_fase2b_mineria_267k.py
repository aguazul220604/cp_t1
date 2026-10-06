# Dataiku Python recipe: fase2b_mineria_267k
# REGLA DE ORO: lee SOLO la columna `name` del 267k. Ignora sus etiquetas.
# In (Flow): dataset_no_validated — se usa solo `name`
# Out (Flow): variantes_lexicas_267k (dataset) + managed folder (fase2b_lexico) con JSON
import argparse
import json
import re
import pandas as pd

try:
    import dataiku
    HAS_DATAIKU = True
except ImportError:
    HAS_DATAIKU = False

IN_DATASET = "dataset_no_validated"
OUT_DATASET = "variantes_lexicas_267k"
OUT_FOLDER = "fase2b_lexico"
OUT_JSON_NAME = "operadores_permitidos.json"

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
    return {
        "underscore": float(s.str.contains("_", regex=False).mean()),
        "guion": float(s.str.contains("-", regex=False).mean()),
        "espacio": float(s.str.contains(" ", regex=False).mean()),
        "punto": float(s.str.contains(r"\.", regex=True).mean()),
        "sin_sep": float((~s.str.contains(r"[_\- .]", regex=True)).mean()),
        "camel": float(s.str.contains(r"[a-z][A-Z]", regex=True).mean()),
        "mayusculas_full": float(s.str.contains(r"^[A-Z0-9 _\-/\.]+$", regex=True).fillna(False).mean()),
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
        cnt = int(low.str.contains(re.escape(c), regex=True).sum())
        if cnt > 0:
            rows.append({"calificador": c, "n_obs": cnt})
    if not rows:
        return pd.DataFrame(columns=["calificador", "n_obs"])
    return pd.DataFrame(rows).sort_values("n_obs", ascending=False).reset_index(drop=True)


def procesar_datos(names: pd.Series):
    sep = detectar_separadores(names)
    fam = minar_familias(names)
    cal = minar_calificadores(names)

    fam_out = fam.rename(columns={"familia": "tipo", "variante": "valor"})[["tipo", "valor", "n_obs"]]
    cal_out = cal.rename(columns={"calificador": "valor"}).assign(tipo="calificador")[["tipo", "valor", "n_obs"]]
    
    sep_out = pd.DataFrame([
        {"tipo": "separador", "valor": k, "n_obs": int(round(v * len(names))) if k != "n" else v}
        for k, v in sep.items() if k != "n"
    ])[["tipo", "valor", "n_obs"]]

    out = pd.concat([fam_out, cal_out, sep_out], ignore_index=True)
    payload = {
        "separadores": sep,
        "familias_observadas": fam.to_dict("records"),
        "calificadores_observados": cal.to_dict("records")
    }
    return out, payload, sep, fam, cal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="267k.csv")
    ap.add_argument("--output", default="variantes_lexicas_267k.csv")
    ap.add_argument("--dict", default="operadores.json", dest="dict_path")
    a, _ = ap.parse_known_args()

    if HAS_DATAIKU:
        # --- Modo Dataiku DSS ---
        df = dataiku.Dataset(IN_DATASET).get_dataframe()
        names = df["name"] if "name" in df.columns else df.iloc[:, 0]
        
        out, payload, sep, fam, cal = procesar_datos(names)

        # 1. Guardar Dataset en el Flow
        dataiku.Dataset(OUT_DATASET).write_with_schema(out)

        # 2. Guardar JSON en Managed Folder
        try:
            folder = dataiku.Folder(OUT_FOLDER)
            json_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            folder.upload_data(OUT_JSON_NAME, json_bytes)
            print(f"JSON escrito correctamente en folder '{OUT_FOLDER}/{OUT_JSON_NAME}'")
        except Exception as fe:
            print(f"AVISO: no se pudo escribir en folder '{OUT_FOLDER}' ({fe}). "
                  f"Asegurate de crear el Managed Folder en el Flow y enlazarlo como Output de esta recipe.")

        print(f"OK 2b (Dataiku): {len(names)} names, {len(fam)} variantes familia, "
              f"{len(cal)} calificadores, seps={ {k: round(v, 3) for k, v in sep.items() if k != 'n'} }")
        return

    # --- Modo ejecucion Local ---
    df = pd.read_csv(a.input)
    names = df["name"] if "name" in df.columns else df.iloc[:, 0]
    out, payload, sep, fam, cal = procesar_datos(names)

    out.to_csv(a.output, index=False)
    with open(a.dict_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"OK 2b local: -> {a.output}, {a.dict_path}")


if __name__ == "__main__":
    main()