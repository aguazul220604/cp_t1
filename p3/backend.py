import base64
import dataiku
import pandas as pd
from flask import request, jsonify
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta

# ==========================================
# CONFIGURACIÓN DE RECURSOS EN DATAIKU
# ==========================================
S3_FOLDER_NAME = "S3_Bundle_Backup_Path"
PERSISTENCE_DATASET_NAME = "bundles_cleanup_history"
REPORTS_FOLDER_NAME = "Cleanup_Reports_Folder"

RETENTION_MONTHS = 6  # ventana fija de revisión: últimos 6 meses desde hoy

PERSISTENCE_COLUMNS = [
    "execution_timestamp", "flow", "environment", "server", "project",
    "s3_path", "file_date", "status", "error_message"
]

s3_folder = dataiku.Folder(S3_FOLDER_NAME)


# ==========================================
# HELPERS DE PARSEO DE RUTAS POR FLUJO
# ==========================================

def parse_legacy_path(path):
    """
    Estructura real generada por el script de backup (Legacy):
        {project_name}/project_bundles/{remaining_path}

    NOTA 1: remaining_path conserva la estructura original en disco y NO
    garantiza traer una fecha en el nombre; por eso el orden temporal se
    resuelve siempre con la metadata de S3 (lastModified), nunca con el
    nombre del archivo.

    NOTA 2:
      a) si el mismo nombre de proyecto existe en un legacy PROD y en un
         legacy UAT, sus bundles comparten el mismo prefijo en S3.
      b) la vista "LEGACY FLOW | Histórico de Proyectos" que agregaron
         (con columna "Servidor") NO se puede poblar con datos reales
         mientras el script de backup no escriba esa información en la
         ruta de S3 
    """
    clean = path.strip('/')
    parts = clean.split('/')
    if len(parts) < 2:
        return None
    project = parts[0]
    version_label = '/'.join(parts[2:]) if len(parts) > 2 else parts[-1]
    return {
        "flow": "LEGACY",
        "project": project,
        "version_label": version_label,
    }


def parse_new_path(path):
    """
    Estructura generada por el script de backup (New):
        dataiku/{environment}/{server}/{project}/{timestamp}.zip
    Confirmado con datos reales: el nombre del archivo ya trae la fecha.
    """
    clean = path.strip('/')
    parts = clean.split('/')
    if len(parts) < 5 or parts[0] != 'dataiku':
        return None
    _, environment, server, project, filename = parts[:5]
    version_label = filename.replace('.zip', '')
    return {
        "flow": "NEW",
        "environment": environment,
        "server": server,
        "project": project,
        "version_label": version_label,
    }


def parse_path(path, flow):
    if flow == "LEGACY":
        return parse_legacy_path(path)
    if flow == "NEW":
        return parse_new_path(path)
    return None


def group_key(parsed):
    """Clave de agrupación: en Legacy solo por proyecto; en New por
    ambiente + servidor + proyecto (el mismo nombre de proyecto puede
    repetirse entre servidores/ambientes distintos)."""
    if parsed["flow"] == "LEGACY":
        return (parsed["project"],)
    return (parsed["environment"], parsed["server"], parsed["project"])


# ==========================================
# HELPERS DE PERSISTENCIA
# ==========================================

def load_persistence_df():
    """
    Lee el dataset de persistencia de forma segura.

    A diferencia de la versión anterior, aquí NO se asume que cualquier
    excepción significa "dataset vacío, es la primera corrida" -- solo se
    trata como tal un error cuyo mensaje indique que el dataset todavía no
    tiene schema definido (nunca se ha escrito nada en él). Cualquier otro
    error se re-lanza, para no arriesgar sobrescribir el histórico real.

    RECOMENDACIÓN: para eliminar esta ambigüedad por completo, inicializa
    el dataset una sola vez escribiendo un DataFrame vacío con
    PERSISTENCE_COLUMNS antes de la primera ejecución real. Así
    get_dataframe() siempre regresará un DataFrame válido (con 0 filas la
    primera vez) y este bloque heurístico deja de ser necesario.
    """
    dataset = dataiku.Dataset(PERSISTENCE_DATASET_NAME)
    try:
        df = dataset.get_dataframe()
    except Exception as e:
        msg = str(e).lower()
        if "no columns" in msg or "empty" in msg or "schema" in msg:
            return pd.DataFrame(columns=PERSISTENCE_COLUMNS)
        raise
    if df is None or df.empty:
        return pd.DataFrame(columns=PERSISTENCE_COLUMNS)
    return df


def get_already_processed_paths(df, flow):
    """Rutas que ya tienen una decisión registrada (PRESERVED o DELETED)
    en una ejecución previa, para no volver a mostrarlas en la revisión
    de la corrida actual."""
    if df.empty:
        return set()
    subset = df[(df["flow"] == flow) & (df["status"].isin(["PRESERVED", "DELETED"]))]
    return set(subset["s3_path"].tolist())


# ==========================================
# ENDPOINT: CONSULTAR BUNDLES PENDIENTES DE REVISIÓN
# ==========================================
@app.route('/api/get-s3-bundles', methods=['GET'])
def get_s3_bundles():
    try:
        flow = request.args.get('flow', 'LEGACY').upper()
        if flow not in ("LEGACY", "NEW"):
            return jsonify({"status": "ERROR", "message": "flow debe ser LEGACY o NEW"}), 400

        now = datetime.now(timezone.utc)
        window_start = now - relativedelta(months=RETENTION_MONTHS)

        persistence_df = load_persistence_df()
        already_processed = get_already_processed_paths(persistence_df, flow)

        paths = s3_folder.list_paths_in_partition()

        # Agrupamos primero, para poder decidir "más reciente por grupo"
        groups = {}
        total_bytes = 0

        for p in paths:
            parsed = parse_path(p, flow)
            if parsed is None:
                continue  # ruta que no corresponde a este flujo

            if p in already_processed:
                continue  # ya tiene una decisión registrada en una corrida previa

            details = s3_folder.get_path_details(p)
            size_bytes = details.get('size', 0)
            last_modified_ms = details.get('lastModified', 0)
            file_date = datetime.fromtimestamp(last_modified_ms / 1000.0, tz=timezone.utc)

            if file_date < window_start:
                continue  # fuera de la ventana de revisión de 6 meses

            item = {
                "path": p,
                "sizeBytes": size_bytes,
                "sizeGB": round(size_bytes / (1024 ** 3), 2),
                "fileDate": file_date.strftime("%Y-%m-%d %H:%M:%S"),
                "_fileDateRaw": file_date,  # solo para ordenar, se retira antes de responder
                "versionLabel": parsed["version_label"],
            }

            total_bytes += size_bytes
            key = group_key(parsed)
            groups.setdefault(key, {"parsed": parsed, "items": []})
            groups[key]["items"].append(item)

        # Dentro de cada grupo: el más reciente se conserva por defecto
        discard_bytes = 0
        project_groups = []
        for key, group in groups.items():
            items = group["items"]
            items.sort(key=lambda it: it["_fileDateRaw"], reverse=True)
            for idx, it in enumerate(items):
                it["isDiscardedByDefault"] = (idx != 0)
                if it["isDiscardedByDefault"]:
                    discard_bytes += it["sizeBytes"]
                del it["_fileDateRaw"]

            parsed = group["parsed"]
            project_groups.append({
                "environment": parsed["environment"],
                "server": parsed["server"],
                "project": parsed["project"],
                "versions": items,
            })

        return jsonify({
            "status": "SUCCESS",
            "flow": flow,
            "retentionWindowStart": window_start.strftime("%Y-%m-%d"),
            "metrics": {
                "totalSpaceGB": round(total_bytes / (1024 ** 3), 2),
                "freeSpaceGB": round(discard_bytes / (1024 ** 3), 2),
                "resultSpaceGB": round((total_bytes - discard_bytes) / (1024 ** 3), 2)
            },
            "projects": project_groups
        }), 200

    except Exception as e:
        return jsonify({"status": "ERROR", "message": str(e)}), 500


# ==========================================
# ENDPOINT: HISTÓRICO (versiones ya procesadas / preservadas)
# ==========================================
@app.route('/api/get-historico', methods=['GET'])
def get_historico():
    try:
        flow = request.args.get('flow', 'LEGACY').upper()
        df = load_persistence_df()
        if df.empty:
            return jsonify({"status": "SUCCESS", "flow": flow, "projects": []}), 200

        subset = df[df["flow"] == flow].copy()
        subset = subset.sort_values("execution_timestamp")

        group_cols = ["environment", "server", "project"] if flow == "NEW" else ["project"]

        project_groups = []
        for key_values, group_df in subset.groupby(group_cols):
            if flow == "LEGACY":
                # con un solo campo de agrupación, pandas regresa el valor
                # directo (no una tupla) -- si tu versión de pandas se
                # comporta distinto, ajusta este desempaquetado
                environment, server, project = None, None, key_values
            else:
                environment, server, project = key_values

            versions = [{
                "s3_path": row["s3_path"],
                "executionTimestamp": row["execution_timestamp"],
                "status": row["status"],  # PRESERVED, DELETED, ERROR, NOT_FOUND
            } for _, row in group_df.iterrows()]

            project_groups.append({
                "environment": environment,
                "server": server,
                "project": project,
                "versions": versions,
            })

        return jsonify({"status": "SUCCESS", "flow": flow, "projects": project_groups}), 200

    except Exception as e:
        return jsonify({"status": "ERROR", "message": str(e)}), 500


# ==========================================
# ENDPOINT: EJECUTAR LA LIMPIEZA AUTORIZADA
# ==========================================
@app.route('/api/authorize-cleanup', methods=['POST'])
def authorize_cleanup():
    try:
        data = request.get_json()

        timestamp_str = data.get('timestamp', datetime.now(timezone.utc).isoformat())
        active_flow = data.get('activeFlow', 'UNKNOWN').upper()
        items_to_discard = data.get('discardList', [])   # lista de s3_path (strings)
        items_to_preserve = data.get('preserveList', [])  # lista de s3_path (strings)

        # --- Validación: ningún proyecto debe quedar en cero versiones conservadas ---
        discard_by_group = {}
        for path in items_to_discard:
            parsed = parse_path(path, active_flow)
            if parsed is None:
                continue
            discard_by_group.setdefault(group_key(parsed), []).append(path)

        preserve_by_group = {}
        for path in items_to_preserve:
            parsed = parse_path(path, active_flow)
            if parsed is None:
                continue
            preserve_by_group.setdefault(group_key(parsed), []).append(path)

        empty_groups = [key for key in discard_by_group if not preserve_by_group.get(key)]
        if empty_groups:
            return jsonify({
                "status": "REJECTED",
                "message": "Hay proyectos que quedarían sin ninguna versión conservada.",
                "affectedGroups": [list(k) for k in empty_groups]
            }), 409

        deleted_records = []
        errors = []

        for item_path in items_to_discard:
            clean_s3_path = item_path.strip()
            if not clean_s3_path.startswith('/'):
                clean_s3_path = '/' + clean_s3_path

            parsed = parse_path(item_path, active_flow) or {}

            try:
                if s3_folder.has_path(clean_s3_path):
                    s3_folder.delete_path(clean_s3_path)
                    status, error_message = "DELETED", None
                else:
                    status, error_message = "NOT_FOUND", "El archivo no existe en S3"
            except Exception as e:
                status, error_message = "ERROR", str(e)
                errors.append(f"Error borrando {clean_s3_path}: {error_message}")

            deleted_records.append({
                "execution_timestamp": timestamp_str,
                "flow": active_flow,
                "environment": parsed.get("environment"),
                "server": parsed.get("server"),
                "project": parsed.get("project"),
                "s3_path": clean_s3_path,
                "file_date": None,
                "status": status,
                "error_message": error_message,
            })

        preserved_records = []
        for item_path in items_to_preserve:
            clean_s3_path = item_path.strip()
            if not clean_s3_path.startswith('/'):
                clean_s3_path = '/' + clean_s3_path
            parsed = parse_path(item_path, active_flow) or {}
            preserved_records.append({
                "execution_timestamp": timestamp_str,
                "flow": active_flow,
                "environment": parsed.get("environment"),
                "server": parsed.get("server"),
                "project": parsed.get("project"),
                "s3_path": clean_s3_path,
                "file_date": None,
                "status": "PRESERVED",
                "error_message": None,
            })

        all_event_records = deleted_records + preserved_records

        if all_event_records:
            df_new_records = pd.DataFrame(all_event_records, columns=PERSISTENCE_COLUMNS)
            df_existing = load_persistence_df()
            df_final = pd.concat([df_existing, df_new_records], ignore_index=True)
            dataiku.Dataset(PERSISTENCE_DATASET_NAME).write_with_schema(df_final)

        # --- Reporte CSV: se guarda en Managed Folder Y se regresa en base64 ---
        report_filename = f"reporte_limpieza_{active_flow}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df_report = pd.DataFrame(all_event_records)
        csv_bytes = df_report.to_csv(index=False).encode('utf-8')

        try:
            reports_folder = dataiku.Folder(REPORTS_FOLDER_NAME)
            reports_folder.upload_stream(report_filename, csv_bytes)
        except Exception as repo_err:
            print(f"No se pudo guardar el reporte en la carpeta de reportes: {repo_err}")

        report_base64 = base64.b64encode(csv_bytes).decode('utf-8')

        return jsonify({
            "status": "SUCCESS",
            "message": "Limpieza y reporte procesados correctamente.",
            "deletedCount": len([r for r in deleted_records if r['status'] == 'DELETED']),
            "preservedCount": len(preserved_records),
            "errors": errors,
            "reportFileName": report_filename,
            "reportBase64": report_base64
        }), 200

    except Exception as global_err:
        return jsonify({"status": "ERROR", "message": str(global_err)}), 500
