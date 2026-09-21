import datetime
from collections import defaultdict

import dataiku
import dataikuapi
import pandas as pd
from flask import request, jsonify

DATASET_NAME = "instances"

# Umbral determinante: meses sin actividad a partir del cual
# un proyecto es candidato a eliminación.
# Profundidad por defecto (limpieza base). El frontend puede pedir
# una limpieza más profunda (umbral_min=1) y filtrar por buckets.
UMBRAL_MESES_INACTIVIDAD = 4
UMBRAL_MINIMO_PERMITIDO = 1


def _parse_umbral(valor, defecto=UMBRAL_MESES_INACTIVIDAD):
    """Valida un umbral en meses. Fallback a defecto si ausente/inválido."""
    try:
        v = int(valor)
    except Exception:
        return defecto
    if 1 <= v <= 12:
        return v
    return defecto


def clasificar_bucket(meses):
    """Bucket de profundidad: 4 (>=4m, base oscura) .. 1 (>=1m, clara). 0 = fuera de alcance."""
    try:
        m = int(meses)
    except Exception:
        return 0
    if m >= 4:
        return 4
    if m == 3:
        return 3
    if m == 2:
        return 2
    if m == 1:
        return 1
    return 0


def niveles_activos(profundidad):
    """Niveles acumulativos para una profundidad D: [4..D]. Ej D=2 -> [4,3,2]."""
    try:
        d = int(profundidad)
    except Exception:
        d = UMBRAL_MESES_INACTIVIDAD
    if d <= 4:
        return [u for u in (4, 3, 2, 1) if u >= d]
    return [d]


def months_between(fecha_pasada, fecha_ref=None):
    """Meses calendario completos entre fecha_pasada y fecha_ref.

    Ej: 2026-05-15 vs 2026-09-18 -> 4. Usa diferencia calendario
    (anio*12+mes) menos 1 si el día de ref aún no alcanza el día base.
    Devuelve 0 si fecha_pasada es futura o inválida.
    """
    if fecha_pasada is None:
        return 0
    ref = fecha_ref or datetime.datetime.now()
    try:
        meses = (ref.year - fecha_pasada.year) * 12 + (ref.month - fecha_pasada.month)
        if ref.day < fecha_pasada.day:
            meses -= 1
        return max(0, meses)
    except Exception:
        return 0


def _ms_to_datetime(ms):
    try:
        ms = int(ms or 0)
    except Exception:
        return None
    if ms <= 0:
        return None
    try:
        return datetime.datetime.fromtimestamp(ms / 1000.0)
    except Exception:
        return None

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

        if not nombre or not url or not api_key:
            return jsonify({
                "status": "error",
                "message": "Usted no ha completado todos los campos del formulario"
            }), 400

        dataset = dataiku.Dataset(DATASET_NAME)
        df_actual = dataset.get_dataframe()

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

        if int(instancia_id) not in df["id"].values:
            return jsonify({"status": "error", "message": "Instancia no encontrada"}), 404

        idx = df.index[df["id"] == int(instancia_id)].tolist()[0]
        df.loc[idx, "nombre"] = nombre
        df.loc[idx, "url"] = url
        df.loc[idx, "api_key"] = api_key

        dataset.write_with_schema(df)
        return jsonify({"status": "ok"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ==========================================
# OBTENER PROYECTOS INACTIVOS (acumulativo por profundidad)
# Por defecto devuelve >= umbral_min (1) con bucket por proyecto;
# el frontend filtra localmente según la profundidad de cada instancia.
# ==========================================
@app.route("/obtener-proyectos-inactivos", methods=["GET"])
def obtener_proyectos_inactivos():
    try:
        umbral_min = _parse_umbral(
            request.args.get("umbral_min", request.args.get("umbral_meses", 1)),
            1,
        )

        dataset = dataiku.Dataset(DATASET_NAME)
        df_instancias = dataset.get_dataframe()

        if df_instancias.empty:
            return jsonify({"status": "ok", "datos": [], "umbral_min": umbral_min,
                            "umbral_defecto": UMBRAL_MESES_INACTIVIDAD})

        datos_finales = []
        hoy = datetime.datetime.now()

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
                    last_mod_date = _ms_to_datetime(last_mod_ms)
                    if last_mod_date is None:
                        continue

                    # Regla acumulativa: >= umbral_min meses calendario
                    # (no días fijos). El bucket permite al frontend
                    # colorear y filtrar por profundidad de cada instancia.
                    meses_inactivo = months_between(last_mod_date, hoy)

                    if meses_inactivo >= umbral_min:
                        proyectos_inactivos.append({
                            "id_proyecto": p['projectKey'],
                            "nombre_proyecto": p.get('name', p['projectKey']),
                            "ultima_modificacion": last_mod_date.strftime('%Y-%m-%d'),
                            "months_since_last_modified": meses_inactivo,
                            # Estimación preliminar con lastModifiedOn;
                            # /analizar-proyecto refina con jobs+timeline.
                            "months_since_last_activity": meses_inactivo,
                            "bucket": clasificar_bucket(meses_inactivo),
                            "fuente_actividad": "lastModifiedOn",
                            "decision": "Eliminar" if meses_inactivo >= UMBRAL_MESES_INACTIVIDAD else "Revisar"
                        })
            except Exception as ex_instancia:
                print(f"Error conectando a instancia {nombre}: {ex_instancia}")

            if proyectos_inactivos:
                datos_finales.append({
                    "id_instancia": int(id_instancia),
                    "nombre_instancia": nombre,
                    "proyectos": proyectos_inactivos
                })

        return jsonify({
            "status": "ok",
            "datos": datos_finales,
            "umbral_meses": UMBRAL_MESES_INACTIVIDAD,
            "umbral_min": umbral_min,
            "umbral_defecto": UMBRAL_MESES_INACTIVIDAD
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ==========================================
# ANALIZAR PROYECTO (MÉTRICAS Y DATOS PARA GRÁFICAS)
# ==========================================
@app.route("/analizar-proyecto", methods=["POST"])
def analizar_proyecto():
    try:
        data = request.get_json() or {}
        instancia_id = data.get("instancia_id")
        proyecto_id = data.get("proyecto_id")
        # Profundidad de limpieza de esa instancia (4=base .. 1=profunda).
        umbral = _parse_umbral(data.get("umbral_meses"), UMBRAL_MESES_INACTIVIDAD)

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

        owner_login = info_proyecto.get('ownerDisplayName') or info_proyecto.get('ownerLogin') or 'Sin propietario'

        last_mod_ms = info_proyecto.get('versionTag', {}).get('lastModifiedOn', 0)
        last_mod_date = _ms_to_datetime(last_mod_ms)
        last_mod_str = last_mod_date.strftime('%Y-%m-%d') if last_mod_date else "-"

        num_datasets = len(project.list_datasets())
        num_recipes = len(project.list_recipes())
        num_scenarios = len(project.list_scenarios())

        # 2. EXTRAER HISTORIAL DE ACTIVIDAD (jobs + timeline)
        actividad_por_mes = defaultdict(int)
        total_jobs_ejecutados = 0
        total_commits = 0
        ultima_fecha_jobs = None
        ultima_fecha_commits = None

        try:
            jobs = project.list_jobs()
            total_jobs_ejecutados = len(jobs)
            for j in jobs:
                start_ms = j.get('def', {}).get('initiationTimestamp', 0) or j.get('startTime', 0)
                dt = _ms_to_datetime(start_ms)
                if dt:
                    if ultima_fecha_jobs is None or dt > ultima_fecha_jobs:
                        ultima_fecha_jobs = dt
                    mes_str = dt.strftime('%Y-%m')
                    actividad_por_mes[mes_str] += 1
        except Exception as e_jobs:
            print(f"No se pudieron obtener jobs: {e_jobs}")

        try:
            timeline = project.get_timeline()
            items = timeline.get('items', [])
            total_commits = len(items)
            for item in items:
                commit_ms = item.get('timestamp', 0)
                dt = _ms_to_datetime(commit_ms)
                if dt:
                    if ultima_fecha_commits is None or dt > ultima_fecha_commits:
                        ultima_fecha_commits = dt
                    mes_str = dt.strftime('%Y-%m')
                    actividad_por_mes[mes_str] += 1
        except Exception as e_git:
            print(f"No se pudo obtener timeline/git: {e_git}")

        hoy = datetime.datetime.now()

        # Ambas fuentes solicitadas:
        # - lastModifiedOn (metadato barato del listado)
        # - actividad real = max(lastModifiedOn, último job, último commit)
        candidatos = [d for d in (last_mod_date, ultima_fecha_jobs, ultima_fecha_commits) if d]
        fecha_ultima_actividad = max(candidatos) if candidatos else None
        months_since_last_modified = months_between(last_mod_date, hoy)
        months_since_last_activity = months_between(fecha_ultima_actividad, hoy)
        bucket = clasificar_bucket(months_since_last_activity)
        decision = "Eliminar" if months_since_last_activity >= umbral else "Preservar"

        meses_eje = []
        actividad_eje = []

        for i in range(11, -1, -1):
            fecha_mes = hoy - datetime.timedelta(days=i * 30)
            clave_mes = fecha_mes.strftime('%Y-%m')
            etiqueta_mes = fecha_mes.strftime('%b')

            meses_eje.append(etiqueta_mes)
            actividad_eje.append(actividad_por_mes.get(clave_mes, 0))

        activos = niveles_activos(umbral)
        cortes = [{"umbral": u, "idx": 11 - u} for u in activos]
        idx_corte_4_meses = 11 - UMBRAL_MESES_INACTIVIDAD
        idx_corte_umbral = 11 - umbral

        metricas = {
            "jobs_ejecutados": total_jobs_ejecutados,
            "total_datasets": num_datasets,
            "ultima_modificacion": last_mod_str,
            "ultima_actividad": fecha_ultima_actividad.strftime('%Y-%m-%d') if fecha_ultima_actividad else last_mod_str,
            "months_since_last_modified": months_since_last_modified,
            "months_since_last_activity": months_since_last_activity,
            "bucket": bucket,
            "umbral_meses": umbral,
            "niveles_activos": activos,
            "decision": decision,
            "propietario": owner_login,
            "escenarios_ejecutados": num_scenarios,
            "commits": total_commits
        }

        # 3. Datos crudos para que el frontend dibuje las gráficas (sin matplotlib)
        actividad = {
            "meses": meses_eje,
            "valores": actividad_eje,
            "corte_4_meses": idx_corte_4_meses,
            "corte_umbral": idx_corte_umbral,
            "cortes": cortes,
            "umbral_meses": umbral,
            "niveles_activos": activos
        }

        estructura = {
            "datasets": num_datasets,
            "recetas": num_recipes,
            "escenarios": num_scenarios
        }

        return jsonify({
            "status": "ok",
            "metricas": metricas,
            "actividad": actividad,
            "estructura": estructura
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
