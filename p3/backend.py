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

RETENTION_MONTHS = 6  # Archivos creados HACE MÁS de 6 meses entran a limpieza

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
    Estructura Legacy en S3:
        {project_name}/project_bundles/{remaining_path}
    """
    clean = path.strip('/')
    parts = clean.split('/')
    if len(parts) < 2:
        return None
    project = parts[0]
    version_label = '/'.join(parts[2:]) if len(parts) > 2 else parts[-1]
    return {
        "flow": "LEGACY",
        "environment": "N/A",
        "server": "N/A",
        "project": project,
        "version_label": version_label,
    }

def parse_new_path(path):
    """
    Estructura estricta para New Flow en S3:
        dataiku/{environment}/{server}/{project}/{timestamp}.zip
    """
    clean = path.strip('/')
    parts = clean.split('/')
    
    # Validar que tenga exactamente el formato esperado
    if len(parts) < 5 or parts[0] != 'dataiku':
        return None
    
    environment = parts[1]
    server = parts[2]
    project = parts[3]
    filename = parts[4]
    
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
    if parsed["flow"] == "LEGACY":
        return (parsed["project"],)
    return (parsed["environment"], parsed["server"], parsed["project"])


# ==========================================
# HELPERS DE PERSISTENCIA
# ==========================================

def load_persistence_df():
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
        # Umbral: 6 meses hacia atrás desde hoy
        cutoff_date = now - relativedelta(months=RETENTION_MONTHS)

        persistence_df = load_persistence_df()
        already_processed = get_already_processed_paths(persistence_df, flow)

        paths = s3_folder.list_paths_in_partition()

        groups = {}
        total_bytes = 0

        for p in paths:
            parsed = parse_path(p, flow)
            if parsed is None or p in already_processed:
                continue

            details = s3_folder.get_path_details(p)
            size_bytes = details.get('size', 0)
            last_modified_ms = details.get('lastModified', 0)
            file_date = datetime.fromtimestamp(last_modified_ms / 1000.0, tz=timezone.utc)

            # FILTRO CORREGIDO: Se incluyen los archivos creados HACE MÁS DE 6 MESES (> 6 meses de antigüedad)
            if file_date > cutoff_date:
                continue

            item = {
                "path": p,
                "sizeBytes": size_bytes,
                "sizeGB": round(size_bytes / (1024 ** 3), 4),
                "fileDate": file_date.strftime("%Y-%m-%d %H:%M:%S"),
                "_fileDateRaw": file_date,
                "versionLabel": parsed["version_label"],
            }

            total_bytes += size_bytes
            key = group_key(parsed)
            groups.setdefault(key, {"parsed": parsed, "items": []})
            groups[key]["items"].append(item)

        discard_bytes = 0
        project_groups = []
        
        for key, group in groups.items():
            items = group["items"]
            # Ordenar de más reciente a más antiguo
            items.sort(key=lambda it: it["_fileDateRaw"], reverse=True)
            
            # REGLA DE NEGOCIO:
            # La versión más reciente (idx 0) -> Preservada por defecto (isDiscardedByDefault = False)
            # Las versiones anteriores (idx > 0) -> Descartadas por defecto (isDiscardedByDefault = True)
            for idx, it in enumerate(items):
                it["isDiscardedByDefault"] = (idx != 0)
                if it["isDiscardedByDefault"]:
                    discard_bytes += it["sizeBytes"]
                del it["_fileDateRaw"]

            parsed = group["parsed"]
            project_groups.append({
                "environment": parsed.get("environment"),
                "server": parsed.get("server"),
                "project": parsed.get("project"),
                "versions": items,
            })

        # Estructuración para Vista 1 (Separación explícita por Ambientes en New Flow)
        response_data = {
            "status": "SUCCESS",
            "flow": flow,
            "retentionCutoffDate": cutoff_date.strftime("%Y-%m-%d"),
            "metrics": {
                "totalSpaceGB": round(total_bytes / (1024 ** 3), 2),
                "freeSpaceGB": round(discard_bytes / (1024 ** 3), 2),
                "resultSpaceGB": round((total_bytes - discard_bytes) / (1024 ** 3), 2)
            }
        }

        if flow == "NEW":
            response_data["environments"] = {
                "UAT": [p for p in project_groups if p["environment"] == "UAT"],
                "PROD_1": [p for p in project_groups if p["environment"] in ("PROD-1", "PROD_1")]
            }
        else:
            response_data["projects"] = project_groups

        return jsonify(response_data), 200

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
        if subset.empty:
            return jsonify({"status": "SUCCESS", "flow": flow, "projects": []}), 200

        subset = subset.sort_values("execution_timestamp", ascending=False)
        group_cols = ["environment", "server", "project"] if flow == "NEW" else ["project"]

        project_groups = []
        for key_values, group_df in subset.groupby(group_cols, sort=False):
            if flow == "LEGACY":
                environment, server, project = "N/A", "N/A", key_values
            else:
                environment, server, project = key_values

            versions = [{
                "s3_path": row["s3_path"],
                "executionTimestamp": row["execution_timestamp"],
                "status": row["status"],
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
        items_to_discard = data.get('discardList', [])    # Lista de s3_path
        items_to_preserve = data.get('preserveList', [])  # Lista de s3_path

        # Validación: Ningún proyecto puede quedar sin al menos 1 versión conservada
        discard_by_group = {}
        for path in items_to_discard:
            parsed = parse_path(path, active_flow)
            if parsed:
                discard_by_group.setdefault(group_key(parsed), []).append(path)

        preserve_by_group = {}
        for path in items_to_preserve:
            parsed = parse_path(path, active_flow)
            if parsed:
                preserve_by_group.setdefault(group_key(parsed), []).append(path)

        empty_groups = [key for key in discard_by_group if not preserve_by_group.get(key)]
        if empty_groups:
            return jsonify({
                "status": "REJECTED",
                "message": "Operación cancelada: Existen proyectos que quedarían completamente sin versiones conservadas.",
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
                "environment": parsed.get("environment", "N/A"),
                "server": parsed.get("server", "N/A"),
                "project": parsed.get("project", "N/A"),
                "s3_path": clean_s3_path,
                "file_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
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
                "environment": parsed.get("environment", "N/A"),
                "server": parsed.get("server", "N/A"),
                "project": parsed.get("project", "N/A"),
                "s3_path": clean_s3_path,
                "file_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "status": "PRESERVED",
                "error_message": None,
            })

        all_event_records = deleted_records + preserved_records

        if all_event_records:
            df_new_records = pd.DataFrame(all_event_records, columns=PERSISTENCE_COLUMNS)
            df_existing = load_persistence_df()
            df_final = pd.concat([df_existing, df_new_records], ignore_index=True)
            dataiku.Dataset(PERSISTENCE_DATASET_NAME).write_with_schema(df_final)

        # Generación de reporte CSV
        report_filename = f"reporte_limpieza_{active_flow}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df_report = pd.DataFrame(all_event_records)
        csv_bytes = df_report.to_csv(index=False).encode('utf-8')

        try:
            reports_folder = dataiku.Folder(REPORTS_FOLDER_NAME)
            reports_folder.upload_stream(report_filename, csv_bytes)
        except Exception as repo_err:
            print(f"Error al guardar reporte en Managed Folder: {repo_err}")

        report_base64 = base64.b64encode(csv_bytes).decode('utf-8')

        return jsonify({
            "status": "SUCCESS",
            "message": "Limpieza realizada con éxito y registros guardados.",
            "deletedCount": len([r for r in deleted_records if r['status'] == 'DELETED']),
            "preservedCount": len(preserved_records),
            "errors": errors,
            "reportFileName": report_filename,
            "reportBase64": report_base64
        }), 200

    except Exception as global_err:
        return jsonify({"status": "ERROR", "message": str(global_err)}), 500