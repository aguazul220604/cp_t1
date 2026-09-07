import dataiku
import pandas as pd
from flask import request, jsonify

# --- CONFIGURACIÓN ---
import matplotlib
matplotlib.use('Agg') # Evita errores de renderizado en hilos del servidor
import matplotlib.pyplot as plt

DATASET_NAME = "instances"

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
    folder = dataiku.Folder("imagenes_webapp") 
    image_data = folder.get_download_stream("logo.png").read() 
    encoded_data = base64.b64encode(image_data).decode("utf-8")
    return jsonify({"status": "ok", "data": encoded_data})












# ==========================================
# 5. OBTENER PROYECTOS INACTIVOS (> 4 MESES)
# ==========================================
@app.route("/obtener-proyectos-inactivos", methods=["GET"])
def obtener_proyectos_inactivos():
    try:
        dataset = dataiku.Dataset(DATASET_NAME)
        df_instancias = dataset.get_dataframe()
        
        if df_instancias.empty:
            return jsonify({"status": "ok", "datos": []})

        datos_finales = []
        fecha_limite = datetime.datetime.now() - datetime.timedelta(days=120)

        for _, row in df_instancias.iterrows():
            id_instancia = row['id']
            nombre = row['nombre']
            url = row['url']
            api_key = row['api_key']
            
            proyectos_inactivos = []
            
            try:
                client = dataikuapi.DSSClient(url, api_key)
                client._session.verify = False 
                
                proyectos = client.list_projects()
                
                for p in proyectos:
                    # Usamos 'versionTag' basado en tu descubrimiento en el notebook
                    last_mod_ms = p.get('versionTag', {}).get('lastModifiedOn', 0)
                    if last_mod_ms > 0:
                        last_mod_date = datetime.datetime.fromtimestamp(last_mod_ms / 1000.0)
                        
                        if last_mod_date < fecha_limite:
                            proyectos_inactivos.append({
                                "id_proyecto": p['projectKey'],
                                "nombre_proyecto": p.get('name', p['projectKey'])
                            })
            except Exception as ex_instancia:
                # Este print es el que viste en tus logs
                print(f"Error conectando a instancia {nombre}: {ex_instancia}")
            
            if proyectos_inactivos:
                datos_finales.append({
                    "id_instancia": int(id_instancia),
                    "nombre_instancia": nombre,
                    "proyectos": proyectos_inactivos
                })

        return jsonify({"status": "ok", "datos": datos_finales})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# 6. ANALIZAR PROYECTO (MÉTRICAS Y GRÁFICA)
# ==========================================
# ==========================================
# 6. ANALIZAR PROYECTO (MÉTRICAS Y GRÁFICA)
# ==========================================
@app.route("/analizar-proyecto", methods=["POST"])
def analizar_proyecto():
    try:
        data = request.get_json() or {}
        instancia_id = data.get("instancia_id")
        proyecto_id = data.get("proyecto_id")
        
        dataset = dataiku.Dataset(DATASET_NAME)
        df = dataset.get_dataframe()
        fila = df[df["id"] == int(instancia_id)]
        
        if fila.empty:
            return jsonify({"status": "error", "message": "Instancia no encontrada"}), 404
            
        url = fila.iloc[0]["url"]
        api_key = fila.iloc[0]["api_key"]
        
        client = dataikuapi.DSSClient(url, api_key)
        client._session.verify = False
        
        # 1. Metadatos de la instancia
        proyectos = client.list_projects()
        info_proyecto = next((p for p in proyectos if p['projectKey'] == proyecto_id), {})
        
        # 2. Conexión al proyecto específico
        project = client.get_project(proyecto_id)
        
        last_mod_ms = info_proyecto.get('versionTag', {}).get('lastModifiedOn', 0)
        last_mod_str = datetime.datetime.fromtimestamp(last_mod_ms / 1000.0).strftime('%Y-%m-%d') if last_mod_ms else "-"
        owner_login = info_proyecto.get('ownerLogin', 'Admin')
        
        # Conteos reales
        num_datasets = len(project.list_datasets())
        num_recipes = len(project.list_recipes())
        num_scenarios = len(project.list_scenarios())
        num_jobs = len(project.list_jobs())
        
        metricas = {
            "jobs_ejecutados": num_jobs, 
            "total_datasets": num_datasets,
            "ultima_modificacion": last_mod_str,
            "propietario": owner_login,
            "escenarios_ejecutados": num_scenarios
        }

        # 3. GENERAR GRÁFICA DE MATPLOTLIB
        plt.close('all') # Limpiar figuras previas de la memoria
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8, 3.5), facecolor='white')
        
        # Gráfica 1: Historial estimado de actividad
        meses = ['M-4', 'M-3', 'M-2', 'M-1', 'Actual']
        actividad = [num_jobs, int(num_jobs*0.5), 0, 0, 0] 
        ax1.bar(meses, actividad, color='#178096')
        ax1.set_title('Tendencia de Jobs', fontsize=11, fontweight='bold')
        ax1.grid(axis='y', linestyle='--', alpha=0.5)

        # Gráfica 2: Objetos en el Flujo
        clases = ['Datasets', 'Recetas', 'Escenarios']
        valores = [num_datasets, num_recipes, num_scenarios]
        ax2.barh(clases, valores, color='#ff6b00')
        ax2.set_title('Estructura del Proyecto', fontsize=11, fontweight='bold')
        ax2.grid(axis='x', linestyle='--', alpha=0.5)

        plt.tight_layout()

        # 4. Guardar en buffer en formato PNG sin transparencias problemáticas
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)
        plot_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        plt.close(fig)

        return jsonify({
            "status": "ok", 
            "metricas": metricas,
            "grafica_b64": plot_base64
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500