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
# CONFIGURACIÓN Y CONSTANTES
# ==========================================
S3_FOLDER_ID = "S3_Bundle_Backup_Path"
HISTORICAL_DATASET_NAME = "historical"
SIX_MONTHS_AGO = datetime.now() - timedelta(days=180)

# Mapeo de servidores para New Flow
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

    """
    Parsear rutas de S3 y devolver diccionario con un esquema homogéneo.
    Campos estandarizados: flow, env, nickname, proyecto, filename
    """
    clean_path = path.lstrip("/")
    parts = clean_path.split("/")
    
    # -------------------------------------------------------------
    # ESTRUCTURA NEW FLOW: dataiku/{SERVER_ID}/{PROJECT_KEY}/{ZIP_NAME}
    # -------------------------------------------------------------
    if len(parts) >= 4 and parts[0] == "dataiku":
        server_id = parts[1]
        project = parts[2]
        filename = parts[3]
        
        # Resolver Ambiente y Nickname desde el diccionario global NEW_FLOW_SERVERS
        env, nickname = NEW_FLOW_SERVERS.get(server_id, ("DESCONOCIDO", server_id))
        
        return {
            "flow": "NEW",
            "env": env,              
            "nickname": nickname,    
            "proyecto": project,     
            "filename": filename    
        }
    
    # -------------------------------------------------------------
    # ESTRUCTURA LEGACY FLOW: {PROJECT_KEY}/project_bundles/{ZIP_NAME}
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
        if creation_date < SIX_MONTHS_AGO:
            size_mb = round(file_size_bytes / (1024 * 1024), 2)
            
            # Formato estandarizado de salida
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
    Ejecutar la purga física en S3 de los marcados como 'Descartado',
    actualizar el dataset 'historical' con los 'Conservado' y generar
    el reporte CSV de cambios del período actual.
    """
    data = request.get_json()
    items = data.get("bundles", [])
    
    folder = dataiku.Folder(S3_FOLDER_ID)
    current_period = datetime.now().strftime("%Y-%m-%d")
    
    to_delete = [b for b in items if b.get("estado") == "Descartado"]
    to_preserve = [b for b in items if b.get("estado") == "Conservado"]
    
    # Borrado en S3
    deleted_log = []
    for b in to_delete:
        try:
            folder.delete_path(b["s3_path"])
            b["action"] = "ELIMINADO"
            deleted_log.append(b)
        except Exception as e:
            b["action"] = f"ERROR: {str(e)}"
            deleted_log.append(b)
            
    # Actualizar dataset 'historical'
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
    
    # Generar CSV del periodo actual
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
    # Generar y descargar reporte CSV global del repositorio S3 y sus estados
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