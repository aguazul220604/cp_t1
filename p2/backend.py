import dataiku
import pandas as pd
from flask import request, jsonify

# 1. Cargar el modelo guardado en el flujo de Dataiku
model = dataiku.Model("PII_PREDICT_MODEL")
predictor = model.get_predictor()


# 2. Endpoint único para procesamiento de tablas
@app.route('/process_table', methods=['POST'])
def process_table():
    try:
        if 'file' not in request.files:
            return jsonify({"status": "error", "message": "No se subió ningún archivo"}), 400

        file = request.files['file']
        filename = file.filename.lower()

        # Lectura del archivo enviado desde el frontend
        if filename.endswith('.csv'):
            df = pd.read_csv(file)
        elif filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(file)
        else:
            return jsonify({"status": "error", "message": "Formato no soportado (sólo CSV/Excel)"}), 400

        # Construir matriz de características por columna
        features_list = []
        for col_name in df.columns:
            features_list.append({
                "Grupo técnico": "FRONTEND_UPLOAD",
                "Conjunto de datos": filename,
                "Nombre": str(col_name),
                "Tipo nativo": str(df[col_name].dtype),
                "Descripción": f"Columna {col_name} en {filename}",
                "texto_completo": f"{col_name} {df[col_name].dtype}",
                "PII Indicator": "false",
                "Acepta valores Null": str(df[col_name].isnull().any()),
                "PII_Indicator_clean": "FALSE",
                "target": 0
            })

        df_features = pd.DataFrame(features_list)

        # Ejecutar inferencia batch con el modelo LightGBM
        predictions = predictor.predict(df_features)

        # Estructurar resultado para el frontend
        columns_analysis = []
        for i, col_name in enumerate(df.columns):
            pred_val = predictions.iloc[i].get('prediction', 0)
            is_pii = True if str(pred_val).lower() in ['1', 'true'] else False

            # Extracción de probabilidad
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

        # Muestra de las primeras 10 filas de la tabla cargada
        sample_rows = df.head(10).fillna("").to_dict(orient='records')

        return jsonify({
            "status": "success",
            "columns_analysis": columns_analysis,
            "sample_rows": sample_rows
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500