import csv
import hashlib
import io
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_file
import dataiku
import pandas as pd

# ==========================================
# CONFIGURACIÓN Y CONSTANTES
# NOTA: `app` lo provee la Standard WebApp de Dataiku (sección Python).
# ==========================================
S3_FOLDER_ID = "S3_Bundle_Backup_Path"
HISTORICAL_DATASET_NAME = "historical"

# Esquema canónico del dataset 'historical' (PROJECT_REQUIREMENTS.md §4.3):
# [id, s3_path, flow, proyecto, fecha_creacion_s3, fecha_periodo_limpieza, size]
HISTORICAL_COLUMNS = [
    "id", "s3_path", "flow", "proyecto",
    "fecha_creacion_s3", "fecha_periodo_limpieza", "size",
]

VALID_ESTADOS = ("Conservado", "Descartado")


def get_six_months_ago():
    # Se calcula por request para no congelar el corte en el import.
    # 180 días ≈ 6 meses por simplicidad.
    return datetime.now() - timedelta(days=180)


def md5_of_path(s3_path):
    # §4.1: id = hash MD5 de la ruta S3 (estable entre reinicios).
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
    # ESTRUCTURA NEW FLOW: dataiku/{ENV}/{NICKNAME}/{PROJECT_KEY}/{ZIP_NAME}
    # Ejemplo: dataiku/UAT/DKUD/AE93384SANDBOX/2026-08-20_153638.zip
    # -------------------------------------------------------------
    if len(parts) >= 5 and parts[0] == "dataiku":
        env = parts[1]        # "UAT" o "PROD-1"
        nickname = parts[2]   # "DKUD", "DKUF", etc.
        project = parts[3]    # "AE93384SANDBOX", etc.
        filename = parts[4]   # "2026-08-20_153638.zip"

        return {
            "flow": "NEW",
            "env": env,
            "nickname": nickname,
            "proyecto": project,
            "filename": filename
        }

    # -------------------------------------------------------------
    # ESTRUCTURA LEGACY FLOW: Todo lo opuesto a la estructura de arriba
    # Ejemplo: {PROJECT_KEY}/project_bundles/{ZIP_NAME} o cualquier otra estructura Legacy
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

    # Manejo de cualquier otra estructura de respaldos Legacy
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


def fetch_s3_bundles():
    # Escanea el Folder administrado en S3, aplicar el parser estandarizado y filtrar únicamente los bundles > 6 meses
    folder = dataiku.Folder(S3_FOLDER_ID)
    paths = folder.list_paths_in_partition()
    bundles = []

    for path in paths:
        if not path.endswith(".zip"):
            continue

        meta = parse_s3_path(path)
        if not meta:
            continue

        details = folder.get_path_details(path)
        last_modified_ms = details.get("lastModified", 0)
        file_size_bytes = details.get("size", 0)

        creation_date = datetime.fromtimestamp(last_modified_ms / 1000.0)

        # Filtro por regla de 6 meses
        if creation_date < get_six_months_ago():
            size_mb = round(file_size_bytes / (1024 * 1024), 2)

            # Formato estandarizado de salida (§4.3: fecha_creacion_s3, size)
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
    s3_bundles = fetch_s3_bundles()
    historical = get_historical_records()
    historical_paths = {h["s3_path"] for h in historical if "s3_path" in h}

    # §4.1/§4.4: excluir de Vistas 1/3 todo bundle ya registrado en 'historical'.
    candidates = [b for b in s3_bundles if b["s3_path"] not in historical_paths]

    # Agrupar por (FLOW, AMBIENTE, NICKNAME, PROYECTO):
    # proyectos con el mismo nombre bajo distintos nicknames son independientes (§1).
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
            # REGLA: únicamente la versión más reciente (idx == 0) queda Conservado.
            item["estado"] = "Conservado" if idx == 0 else "Descartado"
            final_bundles.append(item)

    return jsonify({
        "status": "success",
        "bundles": final_bundles,
        "periodo_ejecucion": datetime.now().strftime("%b %Y"),
        "criterio_antiguedad": "> 6 meses"
    })

@app.route("/get-historical", methods=["GET"])
def api_get_historical():
    """
    Obtiene exclusivamente las filas guardadas en el dataset 'historical'.
    Reconstruye env, nickname y filename a partir de s3_path con parse_s3_path.
    """
    historical = get_historical_records()
    final_bundles = []

    for row in historical:
        path = row.get("s3_path", "")
        meta = parse_s3_path(path) if path else None

        # No defaultear flow a "NEW": si no se puede parsear, conservar el del dataset.
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
    Ejecutar la purga física en S3 de los marcados como 'Descartado',
    actualizar el dataset 'historical' de forma incremental
    (inserta Conservado, borra Descartado) y generar el reporte CSV
    del período actual: 7 campos §6.2 + columna Estado.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"status": "error", "message": "JSON inválido"}), 400
    items = data.get("bundles", [])
    if not isinstance(items, list):
        return jsonify({"status": "error", "message": "'bundles' debe ser una lista"}), 400

    # Validar esquema ANTES de mutar S3 o el dataset (evita borrados parciales).
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

    # Borrado en S3 con auditoría por item.
    for b in to_delete:
        try:
            folder.delete_path(b["s3_path"])
            b["Estado"] = "Eliminado"
        except Exception as e:
            b["Estado"] = f"Error: {str(e)}"
    for b in to_preserve:
        b["Estado"] = "Conservado"

    # Actualización incremental de 'historical': conservar lo existente
    # salvo lo marcado Descartado, más los nuevos Conservado.
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

    # CSV del periodo: 7 campos §6.2 + Estado (audita delete_path).
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
    # §6.3: cruzar S3 (> 6m) con 'historical'; CSV = 7 campos + Estado.
    s3_bundles = fetch_s3_bundles()
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
