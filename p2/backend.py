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

        # 3. Construir características basadas en la METADATA (Nombres de columnas)
        features_list = []
        for col_name in df.columns:
            # Como no tenemos descripción en un archivo crudo, el "texto_completo" 
            # será el nombre de la columna limpio (ej. "RFC_CLIENTE" -> "rfc cliente")
            texto_comp = str(col_name).replace("_", " ").lower()

            # Llenamos el diccionario. Ponemos valores por defecto en las demás 
            # variables para cumplir con el esquema que espera el pipeline de Dataiku.
            features_list.append({
                "Grupo técnico": "",
                "Conjunto de datos": str(filename),
                "Nombre": str(col_name),
                "Tipo nativo": str(df[col_name].dtype),
                "Descripción": "", 
                "texto_completo": texto_comp,  # <--- ESTA ES LA CLAVE PARA EL MODELO
                "PII Indicator": "false",
                "Acepta valores Null": "False",
                "PII_Indicator_clean": "FALSE",
                "target": 0
            })

        df_features = pd.DataFrame(features_list)

        # 4. Ejecutar predicción con tu modelo LightGBM
        predictions = predictor.predict(df_features)

        # 5. Mapear resultados para la interfaz
        columns_analysis = []
        for i, col_name in enumerate(df.columns):
            row_pred = predictions.iloc[i]
            
            # Obtener la predicción binaria
            pred_val = row_pred.get('prediction', 0)
            is_pii = True if str(pred_val).lower() in ['1', 'true'] else False

            # Obtener probabilidad para mostrar el porcentaje
            prob_pii = 0.5
            if 'proba_1' in predictions.columns:
                prob_pii = float(row_pred['proba_1'])
            elif 'probas' in predictions.columns and isinstance(row_pred['probas'], dict):
                prob_pii = float(row_pred['probas'].get('1', 0.5))
            else:
                prob_pii = 0.95 if is_pii else 0.05

            columns_analysis.append({
                "name": str(col_name),
                "description": f"Analizado como: '{df_features.iloc[i]['texto_completo']}'",
                "is_pii": is_pii,
                "pii_probability": round(prob_pii, 4)
            })

        # 6. Muestra de las primeras 10 filas para la vista previa en la tabla
        sample_df = df.head(10).astype(str).fillna("")
        sample_rows = sample_df.to_dict(orient='records')

        return jsonify({
            "status": "success",
            "columns_analysis": columns_analysis,
            "sample_rows": sample_rows
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500