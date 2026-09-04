import dataiku
import pandas as pd
from flask import request, jsonify

DATASET_NAME = "personas_registradas"

# ==========================================
# 1. OBTENER LISTA DE INSTANCIAS (GET)
# ==========================================
@app.route("/obtener-instancias", methods=["GET"])
def obtener_instancias():
    try:
        dataset = dataiku.Dataset(DATASET_NAME)
        df = dataset.get_dataframe()

        # Si el dataset está vacío, devolver lista vacía
        if df.empty:
            return jsonify({"status": "ok", "instancias": []})

        # Generar o asegurar un ID único para la tabla en JS si no existe
        if "id" not in df.columns:
            df["id"] = df.index + 1

        instancias = df.to_dict(orient="records")
        return jsonify({"status": "ok", "instancias": instancias})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# 2. REGISTRAR NUEVA INSTANCIA (POST)
# ==========================================
@app.route("/registrar-instancia", methods=["POST"])
def registrar_instancia():
    try:
        data = request.get_json() or {}
        nombre = data.get("nombre", "").strip()
        url = data.get("url", "").strip()
        api_key = data.get("api_key", "").strip()

        # Validación en Backend (Frame 3)
        if not nombre or not url or not api_key:
            return jsonify({
                "status": "error", 
                "message": "Usted no ha completado todos los campos del formulario"
            }), 400

        dataset = dataiku.Dataset(DATASET_NAME)
        df_actual = dataset.get_dataframe()

        # Generar ID
        nuevo_id = 1 if df_actual.empty else len(df_actual) + 1

        nuevo_registro = pd.DataFrame([{
            "id": nuevo_id,
            "nombre": nombre,
            "url": url,
            "api_key": api_key
        }])

        df_final = pd.concat([df_actual, nuevo_registro], ignore_index=True)
        dataset.write_with_schema(df_final)

        return jsonify({"status": "ok"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# 3. ELIMINAR INSTANCIA (POST/DELETE)
# ==========================================
@app.route("/eliminar-instancia", methods=["POST"])
def eliminar_instancia():
    try:
        data = request.get_json() or {}
        instancia_id = data.get("id")

        if instancia_id is None:
            return jsonify({"status": "error", "message": "ID no proporcionado"}), 400

        dataset = dataiku.Dataset(DATASET_NAME)
        df = dataset.get_dataframe()

        # Filtrar removiendo el ID
        df_filtrado = df[df["id"] != int(instancia_id)]

        dataset.write_with_schema(df_filtrado)
        return jsonify({"status": "ok"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
    
    
    # ==========================================
# 4. ACTUALIZAR INSTANCIA (POST)
# ==========================================
@app.route("/actualizar-instancia", methods=["POST"])
def actualizar_instancia():
    try:
        data = request.get_json() or {}
        instancia_id = data.get("id")
        nombre = data.get("nombre", "").strip()
        url = data.get("url", "").strip()
        api_key = data.get("api_key", "").strip()

        if instancia_id is None or not nombre or not url or not api_key:
            return jsonify({
                "status": "error", 
                "message": "Usted no ha completado todos los campos del formulario"
            }), 400

        dataset = dataiku.Dataset(DATASET_NAME)
        df = dataset.get_dataframe()

        # Verificar si el registro existe
        if int(instancia_id) not in df["id"].values:
            return jsonify({"status": "error", "message": "Instancia no encontrada"}), 404

        # Actualizar los valores en el DataFrame
        idx = df.index[df["id"] == int(instancia_id)].tolist()[0]
        df.loc[idx, "nombre"] = nombre
        df.loc[idx, "url"] = url
        df.loc[idx, "api_key"] = api_key

        dataset.write_with_schema(df)
        return jsonify({"status": "ok"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
    
@app.route('/obtener-imagen')
def obtener_imagen():
    folder = dataiku.Folder("imagenes_webapp") # Reemplaza con el nombre real de tu Managed Folder
    image_data = folder.get_download_stream("logo.png").read() # Reemplaza con el nombre real de tu archivo
    encoded_data = base64.b64encode(image_data).decode("utf-8")
    return jsonify({"status": "ok", "data": encoded_data})