import dataiku
import pandas as pd
import json
from flask import request, jsonify
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# ==========================================
# CONFIGURACIÓN DE RECURSOS EN DATAIKU
# ==========================================
# Managed Folder de S3 donde residen los bundles 
S3_FOLDER_NAME = "S3_Bundle_Backup_Path"

# Managed Dataset de Dataiku para la persistencia del histórico
PERSISTENCE_DATASET_NAME = "bundles_cleanup_history"

# Managed Folder para guardar reportes CSV 
REPORTS_FOLDER_NAME = "Cleanup_Reports_Folder"

# Conexiones a los objetos de Dataiku
s3_folder = dataiku.Folder(S3_FOLDER_NAME)


# ==========================================
# ENDPOINT DE EJECUCIÓN Y LIMPIEZA
# ==========================================
@app.route('/api/authorize-cleanup', methods=['POST'])
def authorize_cleanup():
    try:
        # 1. Obtener el payload enviado desde JavaScript
        data = request.get_json()
        
        timestamp_str = data.get('timestamp', datetime.utcnow().isoformat())
        active_flow = data.get('activeFlow', 'UNKNOWN')
        metrics = data.get('metrics', {})
        details = data.get('details', {})
        
        items_to_discard = details.get('discardList', [])
        items_to_preserve = details.get('preserveList', [])
        
        deleted_records = []
        errors = []

        # 2. Proceder con el borrado en S3
        for item_path in items_to_discard:
            # Normalizar la ruta del archivo o carpeta en S3
            clean_s3_path = item_path.strip()
            
            # Garantizar el formato de ruta S3
            if not clean_s3_path.startswith('/'):
                clean_s3_path = '/' + clean_s3_path

            try:
                # Eliminación física en el bucket S3 vía API de Dataiku
                if s3_folder.has_path(clean_s3_path):
                    s3_folder.delete_path(clean_s3_path)
                    
                    deleted_records.append({
                        "execution_timestamp": timestamp_str,
                        "flow": active_flow,
                        "s3_path": clean_s3_path,
                        "status": "DELETED",
                        "error_message": None
                    })
                else:
                    # El elemento no existía previamente en S3
                    deleted_records.append({
                        "execution_timestamp": timestamp_str,
                        "flow": active_flow,
                        "s3_path": clean_s3_path,
                        "status": "NOT_FOUND",
                        "error_message": "El archivo no existe en S3"
                    })
            except Exception as e:
                err_msg = str(e)
                errors.append(f"Error borrando {clean_s3_path}: {err_msg}")
                deleted_records.append({
                    "execution_timestamp": timestamp_str,
                    "flow": active_flow,
                    "s3_path": clean_s3_path,
                    "status": "ERROR",
                    "error_message": err_msg
                })

        # Registrar también los ítems explícitamente preservados en el histórico
        preserved_records = []
        for item_path in items_to_preserve:
            clean_s3_path = item_path.strip()
            if not clean_s3_path.startswith('/'):
                clean_s3_path = '/' + clean_s3_path
                
            preserved_records.append({
                "execution_timestamp": timestamp_str,
                "flow": active_flow,
                "s3_path": clean_s3_path,
                "status": "PRESERVED",
                "error_message": None
            })

        # 3. Guardar registros en el Managed Dataset de Persistencia
        all_event_records = deleted_records + preserved_records
        if all_event_records:
            df_new_records = pd.DataFrame(all_event_records)
            
            # Conectar y escribir en el Managed Dataset
            persistence_dataset = dataiku.Dataset(PERSISTENCE_DATASET_NAME)
            
            try:
                # Intentar concatenar con el histórico existente
                df_existing = persistence_dataset.get_dataframe()
                df_final = pd.concat([df_existing, df_new_records], ignore_index=True)
            except Exception:
                # Si el Dataset está vacío o es la primera ejecución
                df_final = df_new_records

            persistence_dataset.write_with_schema(df_final)

        # 4. Generar el reporte CSV
        report_filename = f"reporte_limpieza_{active_flow}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df_report = pd.DataFrame(all_event_records)
        
        # Opción A: Guardar el CSV en un Managed Folder 
        try:
            reports_folder = dataiku.Folder(REPORTS_FOLDER_NAME)
            csv_bytes = df_report.to_csv(index=False).encode('utf-8')
            reports_folder.upload_stream(report_filename, csv_bytes)
        except Exception as repo_err:
            print(f"No se pudo guardar el reporte en la carpeta de reportes: {repo_err}")

        # 5. Responder al Frontend con la confirmación
        return jsonify({
            "status": "SUCCESS",
            "message": "Limpieza y reporte procesados correctamente.",
            "metrics": metrics,
            "deletedCount": len([r for r in deleted_records if r['status'] == 'DELETED']),
            "preservedCount": len(preserved_records),
            "errors": errors,
            "reportFileName": report_filename
        }), 200

    except Exception as global_err:
        return jsonify({
            "status": "ERROR",
            "message": str(global_err)
        }), 500
        
# ==========================================
# NUEVO ENDPOINT: CONSULTAR ESTADO DE S3
# ==========================================
@app.route('/api/get-s3-bundles', methods=['GET'])
def get_s3_bundles():
    try:
        paths = s3_folder.list_paths_in_partition()
        
        # 1. DEFINIR EL UMBRAL DE 6 MESES DESDE LA FECHA ACTUAL
        now = datetime.now()
        six_months_ago = now - relativedelta(months=6)
        
        items = []
        total_bytes = 0
        discard_bytes = 0

        for p in paths:
            # Obtener los metadatos de la ruta en S3 (fecha de última modificación y peso)
            details = s3_folder.get_path_details(p)
            size_bytes = details.get('size', 0)
            
            # Fecha de modificación devuelta por S3 (en milisegundos POSIX)
            last_modified_ms = details.get('lastModified', 0)
            file_date = datetime.fromtimestamp(last_modified_ms / 1000.0)
            
            total_bytes += size_bytes

            # 2. EVALUAR LA REGLA DE LOS 6 MESES
            # Si el archivo es MÁS ANTIGUO que 6 meses, se marca para descarte por defecto
            is_older_than_6_months = file_date < six_months_ago
            
            # (Opcional: Si es la versión más reciente del proyecto, se protege)
            is_default_discard = is_older_than_6_months

            if is_default_discard:
                discard_bytes += size_bytes

            items.append({
                "path": p,
                "sizeBytes": size_bytes,
                "sizeGB": round(size_bytes / (1024**3), 2),
                "fileDate": file_date.strftime("%Y-%m-%d"),
                "isDiscardedByDefault": is_default_discard
            })

        return jsonify({
            "status": "SUCCESS",
            "retentionThresholdDate": six_months_ago.strftime("%Y-%m-%d"),
            "metrics": {
                "totalSpaceGB": round(total_bytes / (1024**3), 2),
                "freeSpaceGB": round(discard_bytes / (1024**3), 2),
                "resultSpaceGB": round((total_bytes - discard_bytes) / (1024**3), 2)
            },
            "items": items
        }), 200

    except Exception as e:
        return jsonify({"status": "ERROR", "message": str(e)}), 500