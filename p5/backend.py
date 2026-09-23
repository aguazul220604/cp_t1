import datetime
from collections import defaultdict

import dataiku
from flask import request, jsonify

# Umbral determinante: meses sin actividad a partir del cual
# un proyecto es candidato a eliminación.
# Profundidad por defecto (limpieza base). El frontend envía
# ?umbral=<profundidad> (1-4) y el backend filtra exacto.
UMBRAL_MESES_INACTIVIDAD = 4


def _get_current_client():
    """Cliente de la instancia actual donde corre la webapp.

    No requiere URL ni API key explícitas: Dataiku resuelve
    el host y la autenticación del contexto actual.
    """
    return dataiku.api_client()


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
# OBTENER PROYECTOS INACTIVOS (instancia actual, filtro exacto)
# Devuelve SOLO proyectos con Decision == Eliminar según la
# actividad real (max lastModifiedOn, último job, último commit).
# Los meses sin actividad son criterio interno, no se exponen.
# ==========================================
@app.route("/obtener-proyectos-inactivos", methods=["GET"])
def obtener_proyectos_inactivos():
    try:
        umbral = _parse_umbral(
            request.args.get("umbral",
                request.args.get("umbral_meses",
                    request.args.get("umbral_min", UMBRAL_MESES_INACTIVIDAD))),
            UMBRAL_MESES_INACTIVIDAD,
        )

        hoy = datetime.datetime.now()
        candidatos = []

        try:
            client = _get_current_client()
            proyectos = client.list_projects()

            for p in proyectos:
                last_mod_ms = p.get('versionTag', {}).get('lastModifiedOn', 0)
                last_mod_date = _ms_to_datetime(last_mod_ms)
                if last_mod_date is None:
                    continue

                # Prefiltro barato: si ni lastModifiedOn alcanza el umbral,
                # tampoco lo hará la actividad real (max >= lastModifiedOn
                # solo puede ser más reciente, nunca más antigua).
                # Ojo: esto descarta rápido, pero la decisión final
                # siempre se confirma con jobs+timeline.
                if months_between(last_mod_date, hoy) < umbral:
                    continue

                try:
                    project = client.get_project(p['projectKey'])
                except Exception:
                    continue

                ultima_fecha_jobs = None
                ultima_fecha_commits = None

                try:
                    for j in project.list_jobs():
                        start_ms = j.get('def', {}).get('initiationTimestamp', 0) or j.get('startTime', 0)
                        dt = _ms_to_datetime(start_ms)
                        if dt and (ultima_fecha_jobs is None or dt > ultima_fecha_jobs):
                            ultima_fecha_jobs = dt
                except Exception as e_jobs:
                    print(f"No se pudieron obtener jobs de {p.get('projectKey')}: {e_jobs}")

                try:
                    items = (project.get_timeline() or {}).get('items', [])
                    for item in items:
                        dt = _ms_to_datetime(item.get('timestamp', 0))
                        if dt and (ultima_fecha_commits is None or dt > ultima_fecha_commits):
                            ultima_fecha_commits = dt
                except Exception as e_git:
                    print(f"No se pudo obtener timeline de {p.get('projectKey')}: {e_git}")

                cands = [d for d in (last_mod_date, ultima_fecha_jobs, ultima_fecha_commits) if d]
                fecha_ultima_actividad = max(cands) if cands else None
                meses_inactivo = months_between(fecha_ultima_actividad, hoy)

                # Solo Eliminar llega al frontend; Preservar ni se lista.
                if meses_inactivo >= umbral:
                    last_mod_str = last_mod_date.strftime('%Y-%m-%d') if last_mod_date else "-"
                    candidatos.append({
                        "_orden": meses_inactivo,
                        "id_proyecto": p['projectKey'],
                        "nombre_proyecto": p.get('name', p['projectKey']),
                        "ultima_modificacion": last_mod_str,
                        "bucket": clasificar_bucket(meses_inactivo),
                    })
        except Exception as ex_instancia:
            print(f"Error conectando a instancia actual: {ex_instancia}")
            return jsonify({"status": "error", "message": str(ex_instancia)}), 500

        candidatos.sort(key=lambda x: x["_orden"], reverse=True)
        for c in candidatos:
            c.pop("_orden", None)

        return jsonify({
            "status": "ok",
            "datos": candidatos,
            "umbral_meses": umbral,
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
        proyecto_id = data.get("proyecto_id")
        # Profundidad de limpieza seleccionada (4=base .. 1=profunda).
        umbral = _parse_umbral(data.get("umbral_meses"), UMBRAL_MESES_INACTIVIDAD)

        if not proyecto_id:
            return jsonify({"status": "error", "message": "proyecto_id no proporcionado"}), 400

        client = _get_current_client()

        # 1. Metadatos del proyecto
        proyectos = client.list_projects()
        info_proyecto = next((p for p in proyectos if p['projectKey'] == proyecto_id), {})

        if not info_proyecto:
            return jsonify({"status": "error", "message": "Proyecto no encontrado"}), 404

        project = client.get_project(proyecto_id)

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

        # Criterio interno (no visible): meses sin actividad determinan
        # si el proyecto es Eliminar (>= umbral) o Preservar.
        candidatos = [d for d in (last_mod_date, ultima_fecha_jobs, ultima_fecha_commits) if d]
        fecha_ultima_actividad = max(candidatos) if candidatos else None
        months_since_last_activity = months_between(fecha_ultima_actividad, hoy)
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

        # Métricas visibles: solo Jobs, Última modificación y Commits.
        # Meses/Decisión/Propietario son criterio interno (no se muestran),
        # salvo `decision` como señal para retirar un Preservar del listado.
        metricas = {
            "jobs_ejecutados": total_jobs_ejecutados,
            "ultima_modificacion": last_mod_str,
            "commits": total_commits,
            "umbral_meses": umbral,
            "decision": decision,
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
# EJECUTAR LIMPIEZA / BORRADO DE PROYECTOS (instancia actual)
# ==========================================
@app.route("/ejecutar-limpieza", methods=["POST"])
def ejecutar_limpieza():
    try:
        data = request.get_json() or {}
        proyectos_a_limpiar = data.get("proyectos_a_limpiar", [])

        if not proyectos_a_limpiar:
            return jsonify({"status": "ok", "message": "No hay proyectos pendientes por limpiar.", "exitosos": 0, "fallidos": 0})

        client = _get_current_client()

        exitosos = 0
        fallidos = 0
        detalles = []

        for item in proyectos_a_limpiar:
            # Acepta {"proyecto_id": "XXX"} o directamente "XXX".
            proyecto_id = item.get("proyecto_id") if isinstance(item, dict) else item
            if not proyecto_id:
                fallidos += 1
                detalles.append({"proyecto_id": proyecto_id, "status": "error", "message": "proyecto_id no proporcionado"})
                continue

            try:
                project = client.get_project(proyecto_id)
                project.delete(
                    clear_managed_datasets=True,
                    clear_output_managed_folders=True,
                    clear_job_and_scenario_logs=True
                )
                exitosos += 1
                detalles.append({"proyecto_id": proyecto_id, "status": "eliminado"})
            except Exception as ex:
                fallidos += 1
                detalles.append({"proyecto_id": proyecto_id, "status": "error", "message": str(ex)})

        return jsonify({
            "status": "ok",
            "exitosos": exitosos,
            "fallidos": fallidos,
            "detalles": detalles
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
