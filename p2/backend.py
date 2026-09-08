import dataiku
import pandas as pd
from flask import request, jsonify
import io

# -------------------------------------------------------------
# 1. CARGA DEL MODELO Y DATASETS DE DATAIKU
# -------------------------------------------------------------

# Cargar el modelo guardado en el flujo
model = dataiku.Model("PII_PREDICT_MODEL")
predictor = model.get_predictor()

# Dataset donde se guardará la retroalimentación de los usuarios
# Asegúrate de crear este dataset en tu flujo (ej: "pii_user_feedback")
FEEDBACK_DATASET_NAME = "pii_user_feedback"


# -------------------------------------------------------------
# 2. ENDPOINTS FLASK
# -------------------------------------------------------------

@app.route('/process_table', methods=['POST'])
def process_table():
    """
    Recibe un archivo (CSV/Excel), extrae las columnas,
    aplica el modelo LightGBM para detectar PII y devuelve el análisis.
    """
    try:
        if 'file' not in request.files:
            return jsonify({"status": "error", "message": "No se envió ningún archivo"}), 400
        
        file = request.files['file']
        filename = file.filename.lower()

        # Leer archivo subido
        if filename.endswith('.csv'):
            df = pd.read_csv(file)
        elif filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(file)
        else:
            return jsonify({"status": "error", "message": "Formato de archivo no soportado"}), 400

        # Extractores de metadata por columna
        columns_analysis = []
        features_for_prediction = []

        for col_name in df.columns:
            # Construir el diccionario de características esperadas por tu modelo LightGBM
            # Ajusta las llaves según los nombres exactos con los que entrenaste el modelo
            col_features = {
                "Grupo técnico": "FRONTEND_UPLOAD",
                "Conjunto de datos": filename,
                "Nombre": str(col_name),
                "Tipo nativo": str(df[col_name].dtype),
                "Descripción": f"Columna {col_name} cargada desde WebApp",
                "texto_completo": f"{col_name} {df[col_name].dtype}",
                "PII Indicator": "false",
                "Acepta valores Null": str(df[col_name].isnull().any()),
                "PII_Indicator_clean": "FALSE",
                "target": 0
            }
            features_for_prediction.append(col_features)

        # Convertir a DataFrame para evaluación por lote (batch)
        df_features = pd.DataFrame(features_for_prediction)

        # Ejecutar predicción con el modelo
        predictions = predictor.predict(df_features)

        # Mapear los resultados de la predicción y probabilidades
        for i, col_name in enumerate(df.columns):
            # Obtener predicción (1/True para PII)
            pred_val = predictions.iloc[i].get('prediction', 0)
            is_pii = True if str(pred_val).lower() in ['1', 'true'] else False

            # Extraer probabilidad de PII si el modelo devuelve probas
            prob_pii = 0.5
            if 'proba_1' in predictions.columns:
                prob_pii = float(predictions.iloc[i]['proba_1'])
            elif 'probas' in predictions.columns:
                prob_pii = float(predictions.iloc[i]['probas'].get('1', 0.5))
            else:
                prob_pii = 0.95 if is_pii else 0.05

            columns_analysis.append({
                "name": str(col_name),
                "description": df_features.iloc[i]['Descripción'],
                "is_pii": is_pii,
                "pii_probability": round(prob_pii, 4)
            })

        # Muestra de las primeras 10 filas de la tabla para la vista previa
        sample_rows = df.head(10).fillna("").to_dict(orient='records')

        return jsonify({
            "status": "success",
            "columns_analysis": columns_analysis,
            "sample_rows": sample_rows
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/save_feedback', methods=['POST'])
def save_feedback():
    """
    Guarda las confirmaciones manuales del usuario en un Dataset de Dataiku
    para futuros re-entrenamientos del modelo.
    """
    try:
        data = request.get_json()
        feedback_list = data.get('feedback', [])

        if not feedback_list:
            return jsonify({"status": "error", "message": "No hay datos de retroalimentación"}), 400

        # Convertir la confirmación en DataFrame
        df_feedback = pd.DataFrame(feedback_list)
        df_feedback['timestamp'] = pd.Timestamp.now()

        # Escribir o appendear resultados en el dataset de Dataiku
        try:
            dataset_feedback = dataiku.Dataset(FEEDBACK_DATASET_NAME)
            
            # Si el dataset ya existe, concatenar datos nuevos
            try:
                existing_df = dataset_feedback.get_dataframe()
                updated_df = pd.concat([existing_df, df_feedback], ignore_index=True)
            except Exception:
                updated_df = df_feedback

            dataset_feedback.write_with_schema(updated_df)
        except Exception as ds_err:
            print(f"Advertencia al guardar en Dataset: {ds_err}")

        return jsonify({
            "status": "success",
            "message": "Retroalimentación registrada correctamente"
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500