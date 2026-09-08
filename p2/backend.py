import dataiku
import pandas as pd
from flask import request, jsonify

# Load trained Dataiku model
model = dataiku.Model("PII_PREDICT_MODEL")
predictor = model.get_predictor()

@app.route('/process_table', methods=['POST'])
def process_table():
    try:
        if 'file' not in request.files:
            return jsonify({"status": "error", "message": "No file uploaded"}), 400

        file = request.files['file']
        filename = file.filename.lower()

        # Read CSV or Excel
        if filename.endswith('.csv'):
            df = pd.read_csv(file)
        elif filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(file)
        else:
            return jsonify({"status": "error", "message": "Format not supported"}), 400

        # Build feature list for metadata analysis
        features_list = []
        for col_name in df.columns:
            # Format text properly for TF-IDF Vectorizer
            raw_text = str(col_name).replace("_", " ").strip().lower()
            texto_comp = f"columna {raw_text}" if raw_text else "columna vacia"

            features_list.append({
                "Grupo técnico": "P_BANAMEX_V_C",
                "Conjunto de datos": str(filename),
                "Nombre": str(col_name),
                "Tipo nativo": str(df[col_name].dtype),
                "Descripción": texto_comp,
                "texto_completo": texto_comp,
                "PII Indicator": "false",
                "Acepta valores Null": "False",
                "PII_Indicator_clean": "FALSE",
                "target": 0
            })

        df_features = pd.DataFrame(features_list)

        # Run inference
        predictions = predictor.predict(df_features)

        # Extract predictions safely
        columns_analysis = []
        for i, col_name in enumerate(df.columns):
            # Safe extraction regardless of row shape
            if len(predictions) > i:
                row_pred = predictions.iloc[i]
                pred_val = row_pred.get('prediction', 0)
                is_pii = True if str(pred_val).lower() in ['1', 'true'] else False

                prob_pii = 0.5
                if 'proba_1' in predictions.columns:
                    prob_pii = float(row_pred['proba_1'])
                elif 'probas' in predictions.columns and isinstance(row_pred['probas'], dict):
                    prob_pii = float(row_pred['probas'].get('1', 0.5))
                else:
                    prob_pii = 0.95 if is_pii else 0.05
            else:
                is_pii = False
                prob_pii = 0.0

            columns_analysis.append({
                "name": str(col_name),
                "description": f"Analizado: '{df_features.iloc[i]['texto_completo']}'",
                "is_pii": is_pii,
                "pii_probability": round(prob_pii, 4)
            })

        # Table preview (first 10 rows)
        sample_df = df.head(10).astype(str).fillna("")
        sample_rows = sample_df.to_dict(orient='records')

        return jsonify({
            "status": "success",
            "columns_analysis": columns_analysis,
            "sample_rows": sample_rows
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500