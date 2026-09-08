import dataiku
import pandas as pd
import traceback
from flask import request, jsonify

MODEL_NAME = "PII_PREDICT_MODEL"

model = dataiku.Model(MODEL_NAME)
predictor = model.get_predictor()


def read_uploaded_file(file):
    filename = file.filename.lower()
    if filename.endswith(".csv"):
        return pd.read_csv(file)
    elif filename.endswith((".xls", ".xlsx")):
        return pd.read_excel(file)
    else:
        raise ValueError(f"Formato no soportado para '{file.filename}'. Sube archivos .csv o .xlsx.")


def build_features_dataframe(df, source_label):
    features_list = []
    for col_name in df.columns:
        col_str = str(col_name)
        texto_comp = col_str.replace("_", " ").strip().lower()

        features_list.append({
            "Grupo técnico": "FRONTEND_UPLOAD",
            "Conjunto de datos": source_label,
            "Nombre": col_str,
            "Tipo nativo": str(df[col_name].dtype),
            "Descripción": col_str,
            "texto_completo": texto_comp,
            "PII Indicator": "false",
            "Acepta valores Null": "False",
            "PII_Indicator_clean": "FALSE",
            "target": 0,
        })

    return pd.DataFrame(features_list)


@app.route('/process_table', methods=['POST'])
def process_table():
    try:
        files = request.files.getlist('file')

        if not files:
            return jsonify({"status": "error", "message": "No se subió ningún archivo."}), 400

        all_features = []
        skipped = []

        for file in files:
            if file.filename == "":
                continue
            try:
                df = read_uploaded_file(file)
            except ValueError as ve:
                skipped.append(str(ve))
                continue

            if df.shape[1] == 0:
                skipped.append(f"'{file.filename}' no tiene columnas para analizar.")
                continue

            all_features.append(build_features_dataframe(df, file.filename))

        if not all_features:
            return jsonify({
                "status": "error",
                "message": " | ".join(skipped) if skipped else "Ningún archivo pudo procesarse.",
            }), 400

        df_features = pd.concat(all_features, ignore_index=True)

        predictions = predictor.predict(df_features).reset_index(drop=True)

        if len(predictions) != len(df_features):
            raise RuntimeError(
                f"El modelo devolvió {len(predictions)} predicciones para "
                f"{len(df_features)} columnas en total; revisa el preprocesamiento del pipeline."
            )

        columns_analysis = []
        for i in range(len(df_features)):
            row_pred = predictions.iloc[i]
            pred_val = row_pred.get("prediction", 0)
            is_pii = str(pred_val) in ("1", "1.0", "True", "true")

            if "proba_1" in predictions.columns:
                prob_pii = float(row_pred["proba_1"])
            else:
                prob_pii = 0.95 if is_pii else 0.05

            columns_analysis.append({
                "source_file": df_features.iloc[i]["Conjunto de datos"],
                "name": df_features.iloc[i]["Nombre"],
                "is_pii": is_pii,
                "pii_probability": round(prob_pii, 4),
            })

        response = {"status": "success", "columns_analysis": columns_analysis}
        if skipped:
            response["warnings"] = skipped

        return jsonify(response)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500