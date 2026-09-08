import dataiku
import pandas as pd
from flask import request, jsonify

# 1. Cargar el modelo guardado en el flujo de Dataiku
model = dataiku.Model("PII_PREDICT_MODEL")
predictor = model.get_predictor()

@app.route('/process_table', methods=['POST'])
def process_table():
    try:
        if 'file' not in request.files:
            return jsonify({"status": "error", "message": "No se subió ningún archivo"}), 400

        file = request.files['file']
        filename = file.filename.lower()

        # 2. Lectura del archivo enviado desde el frontend
        if filename.endswith('.csv'):
            df = pd.read_csv(file)
        elif filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(file)
        else:
            return jsonify({"status": "error", "message": "Formato no soportado (solo CSV/Excel)"}), 400

        # 3. Construir el DataFrame de entrada EXACTAMENTE como en tu Notebook
        features_list = []
        for col_name in df.columns:
            # Limpiamos el nombre de la columna para simular la metadata
            # Ej: "NOMBRE_BENEFICIARIO" -> "nombre beneficiario"
            texto_comp = str(col_name).replace("_", " ").lower()
            
            # Pasamos ÚNICAMENTE la variable con la que entrenaste
            features_list.append({
                "texto_completo": texto_comp
            })

        df_features = pd.DataFrame(features_list)

        # 4. Ejecutar predicción
        predictions = predictor.predict(df_features)

        # 5. Mapear resultados para la interfaz
        columns_analysis = []
        for i, col_name in enumerate(df.columns):
            row_pred = predictions.iloc[i]
            
            # Obtener la predicción binaria (0 o 1)
            pred_val = row_pred.get('prediction', 0)
            is_pii = True if str(pred_val).lower() in ['1', 'true'] else False

            # Extraer probabilidad
            prob_pii = 0.5
            if 'proba_1' in predictions.columns:
                prob_pii = float(row_pred['proba_1'])
            elif 'probas' in predictions.columns and isinstance(row_pred['probas'], dict):
                prob_pii = float(row_pred['probas'].get('1', 0.5))
            else:
                prob_pii = 0.95 if is_pii else 0.05

            columns_analysis.append({
                "name": str(col_name),
                "description": f"Evaluado mediante NLP como: '{df_features.iloc[i]['texto_completo']}'",
                "is_pii": is_pii,
                "pii_probability": round(prob_pii, 4)
            })

        # 6. Muestra de las primeras 10 filas para la vista previa
        sample_df = df.head(10).astype(str).fillna("")
        sample_rows = sample_df.to_dict(orient='records')

        return jsonify({
            "status": "success",
            "columns_analysis": columns_analysis,
            "sample_rows": sample_rows
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500