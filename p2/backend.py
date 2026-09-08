import dataiku
import pandas as pd
import traceback
from flask import request, jsonify

MODEL_NAME = "PII_PREDICT_MODEL"

# Se carga una sola vez cuando arranca el backend de la webapp, no en cada request
model = dataiku.Model(MODEL_NAME)
predictor = model.get_predictor()


def read_uploaded_file(file):
    """Lee el archivo subido según su extensión. Lanza ValueError con un
    mensaje claro si el formato no es soportado."""
    filename = file.filename.lower()

    if filename.endswith(".csv"):
        return pd.read_csv(file)
    elif filename.endswith((".xls", ".xlsx")):
        return pd.read_excel(file)
    else:
        raise ValueError("Formato no soportado. Sube un archivo .csv o .xlsx.")


def build_features_dataframe(df):
    """Arma un dataframe con una fila por cada columna del archivo subido,
    usando el nombre de columna como texto de entrada para el modelo."""
    features_list = []
    for col_name in df.columns:
        col_str = str(col_name)
        texto_comp = col_str.replace("_", " ").strip().lower()

        features_list.append({
            "Grupo técnico": "FRONTEND_UPLOAD",
            "Conjunto de datos": "uploaded_file",
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
        if 'file' not in request.files:
            return jsonify({"status": "error", "message": "No se subió ningún archivo."}), 400

        file = request.files['file']
        if file.filename == "":
            return jsonify({"status": "error", "message": "El archivo está vacío o no tiene nombre."}), 400

        try:
            df = read_uploaded_file(file)
        except ValueError as ve:
            return jsonify({"status": "error", "message": str(ve)}), 400

        if df.shape[1] == 0:
            return jsonify({"status": "error", "message": "El archivo no tiene columnas para analizar."}), 400

        df_features = build_features_dataframe(df)

        predictions = predictor.predict(df_features).reset_index(drop=True)

        # Validación defensiva: si esto no cuadra, es mejor un mensaje claro
        # que un IndexError críptico más abajo
        if len(predictions) != len(df.columns):
            raise RuntimeError(
                f"El modelo devolvió {len(predictions)} predicciones para "
                f"{len(df.columns)} columnas; revisa el preprocesamiento del pipeline."
            )

        columns_analysis = []
        for i, col_name in enumerate(df.columns):
            row_pred = predictions.iloc[i]

            pred_val = row_pred.get("prediction", 0)
            is_pii = str(pred_val) in ("1", "1.0", "True", "true")

            if "proba_1" in predictions.columns:
                prob_pii = float(row_pred["proba_1"])
            else:
                prob_pii = 0.95 if is_pii else 0.05

            columns_analysis.append({
                "name": str(col_name),
                "is_pii": is_pii,
                "pii_probability": round(prob_pii, 4),
            })

        return jsonify({
            "status": "success",
            "columns_analysis": columns_analysis,
        })

    except Exception as e:
        traceback.print_exc()  # queda registrado completo en la pestaña "Log"
        return jsonify({"status": "error", "message": str(e)}), 500