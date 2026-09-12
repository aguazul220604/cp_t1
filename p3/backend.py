import io
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file
import dataiku

# Requerido por Dataiku para vincular las rutas de Flask
app = Flask(__name__)
import pandas as pd
import dataiku

# 1. CONSTANTES Y CONFIGURACIÓN
S3_FOLDER_NAME = "S3_Bundle_Backup_Path"       # Nombre del Managed Folder en Dataiku
PRESERVATION_DATASET = "bundle_preservation_status" # Dataset administrado de persistencia

# 2. FUNCIONES AUXILIARES
def get_s3_folder():
    return dataiku.Folder(S3_FOLDER_NAME)

def load_persisted_states():
    """Carga los estados de preservación guardados previamente por el usuario."""
    try:
        dataset = dataiku.Dataset(PRESERVATION_DATASET)
        df = dataset.get_dataframe()
        return dict(zip(df['s3_path'], df['status']))
    except Exception:
        return {}

def save_persisted_states(data_list):
    """Guarda o actualiza las decisiones del usuario en el Dataset Administrado."""
    df = pd.DataFrame(data_list)
    dataset = dataiku.Dataset(PRESERVATION_DATASET)
    dataset.write_with_schema(df)

# 3. ENDPOINTS API DE LA WEBAPP

@app.route('/api/get-bundles', methods=['GET'])
def get_bundles():
    """
    Lista el inventario de S3 extrayendo la metadata de modificación directamente 
    del objeto S3 (lastModified) para filtrar y calcular la antigüedad.
    """
    s3_folder = get_s3_folder()
    paths = s3_folder.list_paths_in_partition()
    persisted_states = load_persisted_states()
    
    # Límite de antigüedad (6 meses atrás para producción, parametrizable)
    cutoff_date = datetime.now() - timedelta(days=180)
    inventory = []

    for path in paths:
        clean_path = path.lstrip('/')
        
        # 1. Extracción de Metadatos reales desde S3
        details = s3_folder.get_path_details(clean_path)
        last_modified_ms = details.get("lastModified")
        
        if not last_modified_ms:
            continue
            
        last_modified_dt = datetime.fromtimestamp(last_modified_ms / 1000.0)
        size_bytes = details.get("size", 0)
        size_gb = round(size_bytes / (1024 ** 3), 4)

        # 2. Parsing de estructura de rutas
        parts = clean_path.split('/')
        
        if clean_path.startswith("dataiku/"):
            # New Flow: dataiku/{ENV}/{SERVER}/{PROJECT}/{BUNDLE_ID}.zip
            if len(parts) < 5:
                continue
            flow = "NEW"
            env = parts[1]
            server = parts[2]
            project = parts[3]
            filename = parts[4]
        else:
            # Legacy Flow: {PROJECT}/project_bundles/{FILENAME}
            if len(parts) < 2:
                continue
            flow = "LEGACY"
            env = "LEGACY"
            server = "N/A"
            project = parts[0]
            filename = parts[-1]

        # Filtro de antigüedad por metadatos de S3
        is_candidate = last_modified_dt < cutoff_date

        inventory.append({
            "s3_path": clean_path,
            "flow": flow,
            "env": env,
            "server": server,
            "project": project,
            "filename": filename,
            "last_modified": last_modified_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "last_modified_timestamp": last_modified_ms,
            "size_gb": size_gb,
            "is_candidate": is_candidate
        })

    df = pd.DataFrame(inventory)
    if df.empty:
        return jsonify([])

    # Ordenar las versiones de cada proyecto basándose en el lastModified de S3
    df = df.sort_values(by=['project', 'last_modified_timestamp'], ascending=[True, False])

    processed_records = []
    # Aplicación de reglas de estado por defecto (Reciente = Preservado, Antiguo = Descartado)
    for (project, flow), group in df.groupby(['project', 'flow']):
        for idx, row in group.iterrows():
            item = row.to_dict()
            del item['last_modified_timestamp']

            # Respetar decisión del usuario si ya existe en la persistencia
            if item['s3_path'] in persisted_states:
                item['status'] = persisted_states[item['s3_path']]
            else:
                # Regla por defecto: La versión más reciente conservada, las anteriores descartadas
                if idx == group.index[0]:
                    item['status'] = "Preservado"
                else:
                    item['status'] = "Descartado"

            processed_records.append(item)

    return jsonify(processed_records)


@app.route('/api/save-selection', methods=['POST'])
def save_selection():
    """Actualiza la persistencia según los toggles cambiados en el frontend."""
    payload = request.get_json()
    save_persisted_states(payload)
    return jsonify({"status": "success", "message": "Cambios registrados correctamente."})


@app.route('/api/authorize-cleanup', methods=['POST'])
def authorize_cleanup():
    """
    Elimina físicamente los bundles en S3 marcados como 'Descartado' 
    y retorna un archivo CSV de auditoría para su descarga.
    """
    payload = request.get_json()
    s3_folder = get_s3_folder()
    
    deleted_items = []
    updated_persistence = []

    for item in payload:
        s3_path = item['s3_path']
        status = item['status']

        if status == "Descartado":
            try:
                # Borrado directo utilizando el cliente de Dataiku Folder
                s3_folder.delete_path(s3_path)
                item['action_result'] = "ELIMINADO"
                item['execution_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                item['error'] = ""
                deleted_items.append(item)
            except Exception as e:
                item['action_result'] = "ERROR"
                item['execution_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                item['error'] = str(e)
                deleted_items.append(item)
        else:
            updated_persistence.append({
                "s3_path": s3_path,
                "project": item['project'],
                "status": status,
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

    # Guardar estado actualizado en el dataset administrado
    save_persisted_states(updated_persistence)

    # Generar y devolver el CSV de auditoría
    report_df = pd.DataFrame(deleted_items)
    output = io.BytesIO()
    report_df.to_csv(output, index=False, encoding='utf-8')
    output.seek(0)

    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    return send_file(
        output,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"reporte_limpieza_s3_{timestamp_str}.csv"
    )