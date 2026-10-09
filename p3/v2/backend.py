import csv
import hashlib
import io
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_file
import dataiku
import pandas as pd

# ==========================================
# CONFIGURACIÓN Y CONSTANTES
# ==========================================
S3_FOLDER_ID = "S3_Bundle_Backup_Path"
HISTORICAL_DATASET_NAME = "historical"
HISTORICAL_COLUMNS = [
    "id", "s3_path", "flow", "proyecto",
    "fecha_creacion_s3", "fecha_periodo_limpieza", "size",
]
VALID_ESTADOS = ("Conservado", "Descartado")
DEFAULT_CUTOFF_DAYS = 180  
NEW_FLOW_EXTENSION = ".zip"


def get_six_months_ago(cutoff_days=DEFAULT_CUTOFF_DAYS):
    # Se calcula por request para no congelar el corte en el import
    try:
        cutoff_days = int(cutoff_days)
    except (TypeError, ValueError):
        cutoff_days = DEFAULT_CUTOFF_DAYS
    if cutoff_days < 0:
        cutoff_days = 0
    return datetime.now() - timedelta(days=cutoff_days)


def get_cutoff_days_from_request():
    try:
        from flask import request as _request
        raw = _request.args.get("cutoff_days", DEFAULT_CUTOFF_DAYS)
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_CUTOFF_DAYS


def is_bundle_path(path, flow=None):
    if not path:
        return False
    if flow == "NEW":
        return path.lower().endswith(NEW_FLOW_EXTENSION)
    if flow == "LEGACY":
        # Exigir al menos un nombre de archivo (no solo carpeta raíz)
        clean = path.lstrip("/").rstrip("/")
        return "/" in clean and not clean.endswith("/")
    # Sin flow (compat): aceptar si parece NEW.zip o cualquier LEGACY potencial
    lowered = path.lower()
    if lowered.endswith(NEW_FLOW_EXTENSION):
        return True
    clean = path.lstrip("/").rstrip("/")
    return "/" in clean and not clean.endswith("/")

def md5_of_path(s3_path):
    # hash MD5 de la ruta S3 (estable entre reinicios)
    return hashlib.md5(s3_path.encode("utf-8")).hexdigest()

# ==========================================
# FUNCIONES HELPER
# ==========================================
def parse_s3_path(path):
    """
    Parsear rutas de S3 y devolver diccionario con un esquema homogéneo.
    Campos estandarizados: flow, env, nickname, proyecto, filename
    """
    clean_path = path.lstrip("/")
    parts = clean_path.split("/")

    # -------------------------------------------------------------
    # ESTRUCTURA NEW FLOW: dataiku/{ENV}/{NICKNAME}/{PROJECT_KEY}/{FILE_NAME}
    # -------------------------------------------------------------
    if len(parts) >= 5 and parts[0] == "dataiku":
        env = parts[1]        
        nickname = parts[2]   
        project = parts[3]  
        filename = "/".join(parts[4:])  
        return {
            "flow": "NEW",
            "env": env,
            "nickname": nickname,
            "proyecto": project,
            "filename": filename
        }

    # -------------------------------------------------------------
    # ESTRUCTURA LEGACY FLOW: {PROJECT_KEY}/... (cualquier subestructura)
    # -------------------------------------------------------------
    elif len(parts) >= 3 and parts[1] == "project_bundles":
        project = parts[0]
        filename = "/".join(parts[2:])

        return {
            "flow": "LEGACY",
            "env": "PROD",
            "nickname": "LEGACY",
            "proyecto": project,
            "filename": filename
        }

    # Cualquier otra estructura Legacy: proyecto = primer segmento raíz
    elif len(parts) >= 2 and parts[0] != "dataiku":
        project = parts[0]
        filename = "/".join(parts[1:])

        return {
            "flow": "LEGACY",
            "env": "PROD",
            "nickname": "LEGACY",
            "proyecto": project,
            "filename": filename
        }

    # Ruta no reconocida
    return None


def fetch_s3_bundles(cutoff_days=DEFAULT_CUTOFF_DAYS):
    # Escanea el Folder administrado en S3, aplicar el parser estandarizado y filtrar únicamente los bundles (default 180 ≈ 6 meses)
    folder = dataiku.Folder(S3_FOLDER_ID)
    paths = folder.list_paths_in_partition()
    bundles = []
    cutoff_date = get_six_months_ago(cutoff_days)

    for path in paths:
        # Parsear primero para respetar flujos
        meta = parse_s3_path(path)
        if not meta:
            continue
        if not is_bundle_path(path, flow=meta.get("flow")):
            continue

        details = folder.get_path_details(path)
        last_modified_ms = details.get("lastModified", 0)
        file_size_bytes = details.get("size", 0)

        creation_date = datetime.fromtimestamp(last_modified_ms / 1000.0)

        # Filtro 
        if creation_date < cutoff_date:
            size_mb = round(file_size_bytes / (1024 * 1024), 2)

            # Formato de salida 
            bundles.append({
                "id": md5_of_path(path),
                "s3_path": path,
                "flow": meta["flow"],
                "env": meta["env"],
                "nickname": meta["nickname"],
                "proyecto": meta["proyecto"],
                "filename": meta["filename"],
                "fecha_creacion_s3": creation_date.strftime("%Y-%m-%d %H:%M:%S"),
                "size": size_mb
            })

    return bundles

# ==========================================
# GESTIÓN DEL HISTORICAL
# ==========================================
def get_historical_records():
    # Leer el dataset administrado 'historical' y retorna un DataFrame
    try:
        dataset = dataiku.Dataset(HISTORICAL_DATASET_NAME)
        df = dataset.get_dataframe()
        return df.to_dict(orient="records")
    except Exception as e:
        # Retornar lista vacía si el dataset aún no se ha inicializado
        return []

def save_historical_records(records):
    # Guardar o actualizar la lista de bundles preservados
    dataset = dataiku.Dataset(HISTORICAL_DATASET_NAME)
    df = pd.DataFrame(records)
    dataset.write_with_schema(df)

# ==========================================
# ENDPOINTS API REST
# ==========================================
@app.route("/scan-bundles", methods=["GET"])
def api_scan_bundles():
    cutoff_days = get_cutoff_days_from_request()
    s3_bundles = fetch_s3_bundles(cutoff_days=cutoff_days)
    historical = get_historical_records()
    historical_paths = {h["s3_path"] for h in historical if "s3_path" in h}
    candidates = [b for b in s3_bundles if b["s3_path"] not in historical_paths]

    # Agrupar por (FLOW, AMBIENTE, NICKNAME, PROYECTO)
    groups = {}
    for b in candidates:
        group_key = (b["flow"], b["env"], b["nickname"], b["proyecto"])
        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(b)

    final_bundles = []

    for group_key, items in groups.items():
        # Ordenar por fecha real de creación (lastModified); fallback a filename.
        items.sort(
            key=lambda x: (x.get("fecha_creacion_s3", ""), x.get("filename", "")),
            reverse=True,
        )

        for idx, item in enumerate(items):
            # la versión más reciente (idx == 0) queda Conservado.
            item["estado"] = "Conservado" if idx == 0 else "Descartado"
            final_bundles.append(item)

    # Criterio dinámico
    if cutoff_days == DEFAULT_CUTOFF_DAYS:
        criterio = "> 6 meses"
    elif cutoff_days == 0:
        criterio = "sin filtro (pruebas)"
    else:
        criterio = f"> {cutoff_days} días"

    return jsonify({
        "status": "success",
        "bundles": final_bundles,
        "periodo_ejecucion": datetime.now().strftime("%b %Y"),
        "criterio_antiguedad": criterio,
        "cutoff_days": cutoff_days
    })

@app.route("/get-historical", methods=["GET"])
def api_get_historical():
    """
    Obtiene exclusivamente las filas guardadas en el dataset 'historical'
    Reconstruye env, nickname y filename a partir de s3_path con parse_s3_path
    """
    historical = get_historical_records()
    final_bundles = []

    for row in historical:
        path = row.get("s3_path", "")
        meta = parse_s3_path(path) if path else None

        # No defaultear flow a "NEW", si no se puede parsear, conservar el del dataset
        flow = row.get("flow", "") or (meta["flow"] if meta else "")

        final_bundles.append({
            "id": str(row.get("id", "")),
            "s3_path": path,
            "flow": flow,
            "env": meta["env"] if meta else "",
            "nickname": meta["nickname"] if meta else "",
            "proyecto": row.get("proyecto", ""),
            "filename": meta["filename"] if meta else "",
            "fecha_creacion_s3": str(row.get("fecha_creacion_s3", "")),
            "fecha_periodo_limpieza": str(row.get("fecha_periodo_limpieza", "")),
            "size": row.get("size", 0),
            "estado": "Conservado"
        })

    return jsonify({
        "status": "success",
        "bundles": final_bundles,
        "periodo_ejecucion": datetime.now().strftime("%b %Y")
    })

@app.route("/authorize-cleanup", methods=["POST"])
def api_authorize_cleanup():
    """
    Ejecutar la purga física en S3 de los marcados como 'Descartado'
    Actualizar el dataset 'historical' de forma incremental
    (inserta Conservado, borra Descartado) Generar el reporte CSV
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"status": "error", "message": "JSON inválido"}), 400
    items = data.get("bundles", [])
    if not isinstance(items, list):
        return jsonify({"status": "error", "message": "'bundles' debe ser una lista"}), 400

    # Validar esquema
    for b in items:
        if not isinstance(b, dict) or not b.get("s3_path") or b.get("estado") not in VALID_ESTADOS:
            return jsonify({
                "status": "error",
                "message": "Cada bundle requiere 's3_path' y estado Conservado/Descartado",
            }), 400

    folder = dataiku.Folder(S3_FOLDER_ID)
    current_period = datetime.now().strftime("%Y-%m-%d")

    to_delete = [b for b in items if b.get("estado") == "Descartado"]
    to_preserve = [b for b in items if b.get("estado") == "Conservado"]

    # Borrado en S3 
    for b in to_delete:
        try:
            folder.delete_path(b["s3_path"])
            b["Estado"] = "Eliminado"
        except Exception as e:
            b["Estado"] = f"Error: {str(e)}"
    for b in to_preserve:
        b["Estado"] = "Conservado"

    # Actualización incremental de 'historical'
    delete_paths = {b["s3_path"] for b in to_delete}
    merged = {}
    for row in get_historical_records():
        sp = row.get("s3_path")
        if sp and sp not in delete_paths:
            merged[sp] = {k: row.get(k, "") for k in HISTORICAL_COLUMNS}
    for b in to_preserve:
        sp = b["s3_path"]
        merged[sp] = {
            "id": b.get("id") or md5_of_path(sp),
            "s3_path": sp,
            "flow": b.get("flow", ""),
            "proyecto": b.get("proyecto", ""),
            "fecha_creacion_s3": b.get("fecha_creacion_s3", b.get("fecha_creacion", "")),
            "fecha_periodo_limpieza": current_period,
            "size": b.get("size", b.get("size_mb", 0)),
        }
    save_historical_records([merged[k] for k in sorted(merged)])

    # CSV del periodo
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=HISTORICAL_COLUMNS + ["Estado"])
    writer.writeheader()

    for b in items:
        sp = b["s3_path"]
        writer.writerow({
            "id": b.get("id") or md5_of_path(sp),
            "s3_path": sp,
            "flow": b.get("flow", ""),
            "proyecto": b.get("proyecto", ""),
            "fecha_creacion_s3": b.get("fecha_creacion_s3", b.get("fecha_creacion", "")),
            "fecha_periodo_limpieza": current_period,
            "size": b.get("size", b.get("size_mb", 0)),
            "Estado": b.get("Estado", b.get("estado", "")),
        })

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"Reporte_Limpieza_{current_period}.csv"
    )

@app.route("/global-report", methods=["GET"])
def api_global_report():
    cutoff_days = get_cutoff_days_from_request()
    s3_bundles = fetch_s3_bundles(cutoff_days=cutoff_days)
    historical = get_historical_records()
    historical_by_path = {h["s3_path"]: h for h in historical if "s3_path" in h}
    current_period = datetime.now().strftime("%Y-%m-%d")

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=HISTORICAL_COLUMNS + ["Estado"])
    writer.writeheader()

    for b in s3_bundles:
        sp = b["s3_path"]
        if sp in historical_by_path:
            h = historical_by_path[sp]
            writer.writerow({
                "id": h.get("id", b["id"]),
                "s3_path": sp,
                "flow": h.get("flow", b["flow"]),
                "proyecto": h.get("proyecto", b["proyecto"]),
                "fecha_creacion_s3": h.get("fecha_creacion_s3", b.get("fecha_creacion_s3", "")),
                "fecha_periodo_limpieza": h.get("fecha_periodo_limpieza", ""),
                "size": h.get("size", b.get("size", 0)),
                "Estado": "Conservado",
            })
        else:
            writer.writerow({
                "id": b["id"],
                "s3_path": sp,
                "flow": b["flow"],
                "proyecto": b["proyecto"],
                "fecha_creacion_s3": b.get("fecha_creacion_s3", ""),
                "fecha_periodo_limpieza": current_period,
                "size": b.get("size", 0),
                "Estado": "Próximo a eliminar",
            })

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"Consulta_Global_S3_{datetime.now().strftime('%Y%m%d')}.csv"
    )
