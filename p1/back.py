import dataiku
import pandas as pd
from flask import request, jsonify

DATASET_NAME = "instances"

# ==========================================
# OBTENER INSTANCIAS 
# ==========================================
@app.route("/obtener-instancias", methods=["GET"])
def obtener_instancias():
    try:
        dataset = dataiku.Dataset(DATASET_NAME)
        df = dataset.get_dataframe()

        if df.empty:
            return jsonify({"status": "ok", "instancias": []})

        if "id" not in df.columns:
            df["id"] = df.index + 1

        instancias = df.to_dict(orient="records")
        return jsonify({"status": "ok", "instancias": instancias})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ==========================================
# REGISTRAR NUEVA INSTANCIA
# ==========================================
@app.route("/registrar-instancia", methods=["POST"])
def registrar_instancia():
    try:
        data = request.get_json() or {}
        nombre = data.get("nombre", "").strip()
        url = data.get("url", "").strip()
        api_key = data.get("api_key", "").strip()

        # Validación 
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
# ELIMINAR INSTANCIA
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

        # Filtrar 
        df_filtrado = df[df["id"] != int(instancia_id)]

        dataset.write_with_schema(df_filtrado)
        return jsonify({"status": "ok"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
    
    
# ==========================================
# ACTUALIZAR INSTANCIA
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

        # Actualizar los valores 
        idx = df.index[df["id"] == int(instancia_id)].tolist()[0]
        df.loc[idx, "nombre"] = nombre
        df.loc[idx, "url"] = url
        df.loc[idx, "api_key"] = api_key

        dataset.write_with_schema(df)
        return jsonify({"status": "ok"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
# ==========================================
# OBTENER PROYECTOS INACTIVOS (> 4 MESES)
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
                    last_mod_ms = p.get('versionTag', {}).get('lastModifiedOn', 0)
                    if last_mod_ms > 0:
                        last_mod_date = datetime.datetime.fromtimestamp(last_mod_ms / 1000.0)
                        
                        if last_mod_date < fecha_limite:
                            proyectos_inactivos.append({
                                "id_proyecto": p['projectKey'],
                                "nombre_proyecto": p.get('name', p['projectKey'])
                            })
            except Exception as ex_instancia:
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
# ANALIZAR PROYECTO (MÉTRICAS Y GRÁFICA)
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
        
        # 1. Metadatos de la instancia y del proyecto
        proyectos = client.list_projects()
        info_proyecto = next((p for p in proyectos if p['projectKey'] == proyecto_id), {})
        
        project = client.get_project(proyecto_id)
        
        # Propietario
        owner_login = info_proyecto.get('ownerDisplayName') or info_proyecto.get('ownerLogin') or 'Sin propietario'
        
        # Última modificación
        last_mod_ms = info_proyecto.get('versionTag', {}).get('lastModifiedOn', 0)
        last_mod_str = datetime.datetime.fromtimestamp(last_mod_ms / 1000.0).strftime('%Y-%m-%d') if last_mod_ms else "-"
        
        # Conteos de estructura
        num_datasets = len(project.list_datasets())
        num_recipes = len(project.list_recipes())
        num_scenarios = len(project.list_scenarios())
        
        # 2. EXTRAER HISTORIAL DE ACTIVIDAD 
        actividad_por_mes = defaultdict(int)
        total_jobs_ejecutados = 0
        total_commits = 0

        # Conteo y fechas de Jobs
        try:
            jobs = project.list_jobs()
            total_jobs_ejecutados = len(jobs)
            for j in jobs:
                start_ms = j.get('def', {}).get('initiationTimestamp', 0) or j.get('startTime', 0)
                if start_ms:
                    mes_str = datetime.datetime.fromtimestamp(start_ms / 1000.0).strftime('%Y-%m')
                    actividad_por_mes[mes_str] += 1
        except Exception as e_jobs:
            print(f"No se pudieron obtener jobs: {e_jobs}")

        # Conteo y fechas de Commits 
        try:
            timeline = project.get_timeline()
            items = timeline.get('items', [])
            total_commits = len(items)
            for item in items:
                commit_ms = item.get('timestamp', 0)
                if commit_ms:
                    mes_str = datetime.datetime.fromtimestamp(commit_ms / 1000.0).strftime('%Y-%m')
                    actividad_por_mes[mes_str] += 1
        except Exception as e_git:
            print(f"No se pudo obtener timeline/git: {e_git}")

        hoy = datetime.datetime.now()
        meses_eje = []
        actividad_eje = []
        
        # Generar últimos 12 meses 
        for i in range(11, -1, -1):
            fecha_mes = hoy - datetime.timedelta(days=i*30)
            clave_mes = fecha_mes.strftime('%Y-%m')
            etiqueta_mes = fecha_mes.strftime('%b') 
            
            meses_eje.append(etiqueta_mes)
            actividad_eje.append(actividad_por_mes.get(clave_mes, 0))

        # hace 4 meses exactos 
        idx_corte_4_meses = 11 - 4 

        # Métricas para la respuesta JSON
        metricas = {
            "jobs_ejecutados": total_jobs_ejecutados, 
            "total_datasets": num_datasets,
            "ultima_modificacion": last_mod_str,
            "propietario": owner_login,
            "escenarios_ejecutados": num_scenarios,
            "commits": total_commits
        }

        # 4. GENERAR GRÁFICAS
        plt.close('all')
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 3.8), facecolor='white')

        # Gráfica 1: Serie Temporal de Actividad
        ax1.plot(meses_eje, actividad_eje, color='#0044ff', linewidth=2, marker='o', markersize=4)
        ax1.axvline(x=idx_corte_4_meses, color='red', linestyle='--', linewidth=1.8, label='Umbral 4M')
        ax1.set_title('Nivel de Actividad (Histórico)', fontsize=10, fontweight='bold')
        ax1.set_ylabel('Acciones (Jobs + Ediciones)', fontsize=8)
        ax1.tick_params(axis='x', rotation=45, labelsize=8)
        ax1.grid(True, linestyle=':', alpha=0.6)
        ax1.legend(loc='upper right', fontsize=7)

        # Gráfica 2: Objetos en el Flujo
        clases = ['Datasets', 'Recetas', 'Escenarios']
        valores = [num_datasets, num_recipes, num_scenarios]
        ax2.barh(clases, valores, color='#0055ff', height=0.5)
        ax2.set_title('Estructura del Proyecto', fontsize=10, fontweight='bold')
        ax2.tick_params(axis='both', labelsize=8)
        ax2.grid(axis='x', linestyle='--', alpha=0.5)

        plt.tight_layout()

        # 5. Convertir gráfica a base64
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=110, bbox_inches='tight')
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

# ==========================================
# EJECUTAR LIMPIEZA / BORRADO DE PROYECTOS
# ==========================================
@app.route("/ejecutar-limpieza", methods=["POST"])
def ejecutar_limpieza():
    try:
        data = request.get_json() or {}
        proyectos_a_limpiar = data.get("proyectos_a_limpiar", [])
        
        if not proyectos_a_limpiar:
            return jsonify({"status": "ok", "message": "No hay proyectos pendientes por limpiar.", "exitosos": 0, "fallidos": 0})

        dataset = dataiku.Dataset(DATASET_NAME)
        df = dataset.get_dataframe()
        
        exitosos = 0
        fallidos = 0
        detalles = []

        for item in proyectos_a_limpiar:
            instancia_id = item.get("instancia_id")
            proyecto_id = item.get("proyecto_id")
            
            fila = df[df["id"] == int(instancia_id)]
            if fila.empty:
                fallidos += 1
                detalles.append({"proyecto_id": proyecto_id, "status": "error", "message": "Instancia no encontrada"})
                continue
                
            url = fila.iloc[0]["url"]
            api_key = fila.iloc[0]["api_key"]
            nombre_inst = fila.iloc[0]["nombre"]
            
            try:
                client = dataikuapi.DSSClient(url, api_key)
                client._session.verify = False
                
                # Obtener el proyecto y ejecutar borrado profundo según los parámetros requeridos
                project = client.get_project(proyecto_id)
                project.delete(
                    clear_managed_datasets=True,
                    clear_output_managed_folders=True,
                    clear_job_and_scenario_logs=True
                )
                exitosos += 1
                detalles.append({"proyecto_id": proyecto_id, "instancia": nombre_inst, "status": "eliminado"})
            except Exception as ex:
                fallidos += 1
                detalles.append({"proyecto_id": proyecto_id, "instancia": nombre_inst, "status": "error", "message": str(ex)})

        return jsonify({
            "status": "ok",
            "exitosos": exitosos,
            "fallidos": fallidos,
            "detalles": detalles
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


