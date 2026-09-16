import os
import re
import csv
import io
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_file
import dataiku
from dataiku import pandasutils as pdu
import pandas as pd

# ==========================================
# CONFIGURACIÓN Y CONSTANTES
# ==========================================
S3_FOLDER_ID = "S3_Bundle_Backup_Path"
HISTORICAL_DATASET_NAME = "historical"
SIX_MONTHS_AGO = datetime.now() - timedelta(days=180)

# Mapeo de servidores para New Flow (por si las rutas traen server_id)
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
    Parsear rutas de S3 soporta ambos formatos:
    1. dataiku/{ENV}/{NICKNAME}/{PROJECT_KEY}/{ZIP_NAME}
    2. dataiku/{SERVER_ID}/{PROJECT_KEY}/{ZIP_NAME}
    """
    clean_path = path.lstrip("/")
    parts = clean_path.split("/")
    
    # -------------------------------------------------------------
    # ESTRUCTURA NEW FLOW
    # -------------------------------------------------------------
    if len(parts) >= 4 and parts[0] == "dataiku":
        # Caso 1: dataiku/UAT/DKUD/PROJECT/file.zip (5 partes)
        if len(parts) >= 5:
            env = parts[1]
            nickname = parts[2]
            project = parts[3]
            filename = parts[4]
        # Caso 2: dataiku/sd-7u15-eilw/PROJECT/file.zip (4 partes)
        else:
            server_id = parts[1]
            project = parts[2]
            filename = parts[3]
            env, nickname = NEW_FLOW_SERVERS.get(server_id, ("DESCONOCIDO", server_id))
        
        return {
            "flow": "NEW",
            "env": env,               
            "nickname": nickname,     
            "proyecto": project,     
            "filename": filename    
        }
    
    # -------------------------------------------------------------
    # ESTRUCTURA LEGACY FLOW
    # -------------------------------------------------------------
    elif len(parts) >= 3 and parts[1] == "project_bundles":
        return {
            "flow": "LEGACY",
            "env": "PROD",        
            "nickname": "LEGACY",   
            "proyecto": parts[0],
            "filename": "/".join(parts[2:])
        }
    elif len(parts) >= 2 and parts[0] != "dataiku":
        return {
            "flow": "LEGACY",
            "env": "PROD",
            "nickname": "LEGACY",
            "proyecto": parts[0],
            "filename": "/".join(parts[1:])
        }
    
    return None

def fetch_s3_bundles():
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
        
        if creation_date < SIX_MONTHS_AGO:
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
# GESTIÓN DEL HISTORICAL
# ==========================================
def get_historical_records():
    try:
        dataset = dataiku.Dataset(HISTORICAL_DATASET_NAME)
        df = dataset.get_dataframe()
        return df.to_dict(orient="records")
    except Exception as e:
        return []

def save_historical_records(records):
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
    
    # CORRECCIÓN DE AGRUPACIÓN:
    # Agrupar por (PROYECTO, AMBIENTE, FLOW) para tratar UAT y PROD-1 de forma independiente
    groups = {}
    for b in s3_bundles:
        group_key = (b["proyecto"], b["env"], b["flow"])
        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(b)
        
    final_bundles = []
    
    for group_key, items in groups.items():
        # Ordenar por fecha de creación descendente (el más reciente primero)
        items.sort(key=lambda x: x["fecha_creacion"], reverse=True)
        
        for idx, item in enumerate(items):
            # 1. Si ya se guardó en 'historical' -> Conservado
            # 2. Si es la versión más reciente dentro de SU ambiente -> Conservado
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
    
@app.route("/get-historical", methods=["GET"])
def api_get_historical():
    historical = get_historical_records()
    final_bundles = []
    
    for row in historical:
        path = row.get("s3_path", "")
        meta = parse_s3_path(path) if path else None
        
        final_bundles.append({
            "id": str(row.get("id", "")),
            "s3_path": path,
            "flow": row.get("flow", meta["flow"] if meta else "NEW"),
            "env": meta["env"] if meta else "",
            "nickname": meta["nickname"] if meta else "",
            "proyecto": row.get("proyecto", ""),
            "filename": meta["filename"] if meta else "",
            "fecha_creacion": str(row.get("fecha_creacion_s3", "")),
            "fecha_periodo_limpieza": str(row.get("fecha_periodo_limpieza", "")),
            "size_mb": row.get("size_mb", 0),
            "estado": "Conservado"
        })
            
    return jsonify({
        "status": "success",
        "bundles": final_bundles,
        "periodo_ejecucion": datetime.now().strftime("%b %Y")
    })
    
@app.route("/authorize-cleanup", methods=["POST"])
def api_authorize_cleanup():
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