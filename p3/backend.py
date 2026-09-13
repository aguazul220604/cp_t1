import os
import re
import csv
import io
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_file
import dataiku
from dataiku import pandasutils as pdu
import pandas as pd

app = Flask(__name__)

# ==========================================
# 1. CONFIGURACIÓN Y CONSTANTES
# ==========================================
S3_FOLDER_ID = "S3_Bundle_Backup_Path"
HISTORICAL_DATASET_NAME = "historical"
SIX_MONTHS_AGO = datetime.now() - timedelta(days=180)

# Mapeo de servidores conocidos para New Flow
NEW_FLOW_SERVERS = {
    'sd-7u15-eilw': ('PROD-1', 'DKUF'),
    'sd-mn7t-ccgf': ('PROD-1', 'RISP'),
    'sd-yslj-ri55': ('PROD-1', 'SEGP'),
    'sd-9r2x-8twu': ('UAT', 'BUAU'),
    'sd-fkub-coxa': ('UAT', 'DKUU'),
    'sd-2edj-g004': ('UAT', 'RISU'),
    'sd-4c64-tuzr': ('UAT', 'SEGU'),
    'sd-zqo7-s06c': ('UAT', 'DKUD')
}

# ==========================================
# 2. FUNCIONES HELPER (PARSER DE S3)
# ==========================================
def parse_s3_path(path):
    """
    Identifica si un objeto en S3 pertenece a NEW FLOW o LEGACY FLOW
    y extrae sus metadatos según la estructura de la ruta.
    """
    parts = path.strip("/").split("/")
    
    # NEW FLOW: dataiku/{ENV}/{NICKNAME}/{PROJECT_KEY}/{ZIP_NAME}
    if len(parts) >= 5 and parts[0] == "dataiku":
        env = parts[1]
        nickname = parts[2]
        project = parts[3]
        filename = parts[4]
        return {
            "flow": "NEW",
            "env": env,
            "nickname": nickname,
            "proyecto": project,
            "filename": filename
        }
    
    # LEGACY FLOW: {PROJECT_KEY}/project_bundles/{REMAINING_PATH}
    elif len(parts) >= 3 and parts[1] == "project_bundles":
        project = parts[0]
        filename = "/".join(parts[2:])
        return {
            "flow": "LEGACY",
            "env": "PROD",  # Asignado por defecto a PROD según reglas
            "nickname": "N/A",
            "proyecto": project,
            "filename": filename
        }
    
    return None

def fetch_s3_bundles():
    """
    Escanea el Managed Folder en S3, obtiene metadata (lastModified, size)
    y filtra únicamente los bundles con antigüedad > 6 meses.
    """
    folder = dataiku.Folder(S3_FOLDER_ID)
    paths = folder.list_paths_in_partition()
    bundles = []
    
    for path in paths:
        if not path.endswith(".zip"):
            continue
            
        details = folder.get_path_details(path)
        last_modified_ms = details.get("lastModified", 0)
        file_size_bytes = details.get("size", 0)
        
        creation_date = datetime.fromtimestamp(last_modified_ms / 1000.0)
        
        # Filtro estático: Antigüedad mayor a 6 meses
        is_older_than_6m = creation_date < SIX_MONTHS_AGO
        
        meta = parse_s3_path(path)
        if meta and is_older_than_6m:
            size_mb = round(file_size_bytes / (1024 * 1024), 2)
            bundles.append({
                "id": str(hash(path)),
                "s3_path": path,
                "flow": meta["flow"],
                "env": meta["env"],
                "nickname": meta["nickname"],
                "proyecto": meta["proyecto"],
                "filename": meta["filename"],
                "fecha_creacion": creation_date.strftime("%Y-%m-%d %H:%M:%S"),
                "size_mb": size_mb
            })
            
    return bundles

# ==========================================
# 3. GESTIÓN DEL DATASET HISTORICAL
# ==========================================
def get_historical_records():
    """Lee el dataset administrado 'historical' y retorna un DataFrame o lista de dicts."""
    try:
        dataset = dataiku.Dataset(HISTORICAL_DATASET_NAME)
        df = dataset.get_dataframe()
        return df.to_dict(orient="records")
    except Exception as e:
        # Retorna lista vacía si el dataset aún no se ha inicializado
        return []

def save_historical_records(records):
    """Guarda o actualiza la lista de bundles preservados en el dataset 'historical'."""
    dataset = dataiku.Dataset(HISTORICAL_DATASET_NAME)
    df = pd.DataFrame(records)
    dataset.write_with_schema(df)

# ==========================================
# 4. ENDPOINTS API REST (FLASK)
# ==========================================

@app.route("/scan-bundles", methods=["GET"])
def api_scan_bundles():
    """
    Obtiene los bundles de S3 (> 6 meses) y los cruza con 'historical'
    para asignar estados iniciales:
    - Versión más reciente del proyecto -> Conservado
    - Versiones anteriores -> Descartado
    - Registrados en 'historical' -> Conservado
    """
    s3_bundles = fetch_s3_bundles()
    historical = get_historical_records()
    historical_paths = {h["s3_path"] for h in historical}
    
    # Agrupar por proyecto para identificar la versión más reciente
    projects_map = {}
    for b in s3_bundles:
        proj = b["proyecto"]
        if proj not in projects_map:
            projects_map[proj] = []
        projects_map[proj].append(b)
        
    final_bundles = []
    
    for proj, items in projects_map.items():
        # Ordenar versiones por fecha descendente
        items.sort(key=lambda x: x["fecha_creacion"], reverse=True)
        
        for idx, item in enumerate(items):
            # Regla de preselección por defecto:
            # 1. Si está previamente en 'historical' -> Conservado
            # 2. Si es la versión más reciente (idx == 0) -> Conservado
            # 3. En otro caso -> Descartado
            if item["s3_path"] in historical_paths or idx == 0:
                item["estado"] = "Conservado"
            else:
                item["estado"] = "Descartado"
                
            final_bundles.append(item)
            
    return jsonify({
        "status": "success",
        "bundles": final_bundles,
        "periodo_ejecucion": datetime.now().strftime("%b %Y"),
        "criterio_antiguedad": "> 6 meses"
    })

@app.route("/authorize-cleanup", methods=["POST"])
def api_authorize_cleanup():
    """
    Ejecuta la purga física en S3 de los marcados como 'Descartado',
    actualiza el dataset 'historical' con los 'Conservado' y genera
    el reporte CSV de cambios del período actual.
    """
    data = request.get_json()
    items = data.get("bundles", [])
    
    folder = dataiku.Folder(S3_FOLDER_ID)
    current_period = datetime.now().strftime("%Y-%m-%d")
    
    to_delete = [b for b in items if b.get("estado") == "Descartado"]
    to_preserve = [b for b in items if b.get("estado") == "Conservado"]
    
    # 1. Borrado físico en S3
    deleted_log = []
    for b in to_delete:
        try:
            folder.delete_path(b["s3_path"])
            b["action"] = "ELIMINADO"
            deleted_log.append(b)
        except Exception as e:
            b["action"] = f"ERROR: {str(e)}"
            deleted_log.append(b)
            
    # 2. Actualizar dataset 'historical'
    historical_records = []
    for b in to_preserve:
        historical_records.append({
            "id": b["id"],
            "s3_path": b["s3_path"],
            "flow": b["flow"],
            "proyecto": b["proyecto"],
            "fecha_creacion_s3": b["fecha_creacion"],
            "fecha_periodo_limpieza": current_period,
            "size_mb": b["size_mb"]
        })
    save_historical_records(historical_records)
    
    # 3. Generar CSV del periodo actual
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["id", "s3_path", "flow", "proyecto", "fecha_creacion", "estado", "size_mb", "fecha_periodo"])
    writer.writeheader()
    
    for b in items:
        writer.writerow({
            "id": b["id"],
            "s3_path": b["s3_path"],
            "flow": b["flow"],
            "proyecto": b["proyecto"],
            "fecha_creacion": b["fecha_creacion"],
            "estado": b.get("estado"),
            "size_mb": b["size_mb"],
            "fecha_periodo": current_period
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
    """Genera y descarga un reporte CSV global del repositorio S3 y sus estados."""
    s3_bundles = fetch_s3_bundles()
    historical = get_historical_records()
    historical_paths = {h["s3_path"] for h in historical}
    
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["id", "s3_path", "flow", "env", "proyecto", "fecha_creacion", "estado", "size_mb"])
    writer.writeheader()
    
    for b in s3_bundles:
        estado = "Preservado" if b["s3_path"] in historical_paths else "Descartado"
        writer.writerow({
            "id": b["id"],
            "s3_path": b["s3_path"],
            "flow": b["flow"],
            "env": b["env"],
            "proyecto": b["proyecto"],
            "fecha_creacion": b["fecha_creacion"],
            "estado": estado,
            "size_mb": b["size_mb"]
        })
        
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"Consulta_Global_S3_{datetime.now().strftime('%Y%m%d')}.csv"
    )