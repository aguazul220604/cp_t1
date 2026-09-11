import json
from datetime import datetime, timedelta
from flask import request, jsonify, send_file
import io
import pandas as pd
import dataiku

# 1. CONSTANTES Y CONFIGURACIÓN
S3_FOLDER_NAME = "S3_Bundle_Backup_Path"  # Nombre del Managed Folder en DSS
PRESERVATION_DATASET = "bundle_preservation_status" # Dataset administrado para persistencia

# Mapa de servidores / hostnames según tu script original
NEW_FLOW_HOST_MAP = {
    'sd-7u15-e17w': ('PROD-1', 'DKUP'),
    'sd-mn7f-ecgf': ('PROD-1', 'RISP'),
    'sd-ys11-r153': ('PROD-1', 'RISP2'),
    'sd-9r2x-8txu': ('UAT', 'DKUD'),
    'sd-fx4s-cose': ('UAT', 'DISU'),
    'sd-2edg-g8bk': ('UAT', 'RISU'),
    'sd-4c6m-tuze': ('UAT', 'SEGU'),
    'sd-zq07-s06c': ('UAT', 'SKUD'),
}

# 2. FUNCIONES AUXILIARES
def get_s3_folder():
    return dataiku.Folder(S3_FOLDER_NAME)

def load_persisted_states():
    """Lee las decisiones de preservación guardadas previamente."""
    try:
        dataset = dataiku.Dataset(PRESERVATION_DATASET)
        df = dataset.get_dataframe()
        # Retorna un diccionario: {s3_path: status}
        return dict(zip(df['s3_path'], df['status']))
    except Exception:
        return {}

def save_persisted_states(data_list):
    """Guarda o actualiza las decisiones en el Dataset Administrado."""
    df = pd.DataFrame(data_list)
    dataset = dataiku.Dataset(PRESERVATION_DATASET)
    dataset.write_with_schema(df)

# 3. ENDPOINTS API DE LA WEBAPP

@app.route('/api/get-bundles', methods=['GET'])
def get_bundles():
    """
    Retorna el inventario de S3 evaluando la regla por defecto:
    - Evalúa antigüedad (> 6 meses).
    - Asigna 'Preservado' al más reciente y 'Descartado' al resto.
    - Sobrescribe el estado si ya existe en el Dataset Administrado.
    """
    s3_folder = get_s3_folder()
    paths = s3_folder.list_paths_in_partition()
    persisted_states = load_persisted_states()
    
    cutoff_date = datetime.now() - timedelta(days=180) # 6 meses atrás
    inventory = []

    for path in paths:
        clean_path = path.lstrip('/')
        parts = clean_path.split('/')
        
        # Identificación del tipo de flujo según la ruta
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
            if len(parts) < 3:
                continue
            flow = "LEGACY"
            env = "LEGACY"
            server = "N/A"
            project = parts[0]
            filename = parts[-1]

        # Obtener metadata del archivo en S3
        info = s3_folder.get_file_details(clean_path)
        last_modified = datetime.fromtimestamp(info['lastModified'] / 1000.0)
        size_gb = round(info['size'] / (1024 ** 3), 2)

        # Regla: considerar candidatos si superan los 6 meses
        is_candidate = last_modified < cutoff_date

        inventory.append({
            "s3_path": clean_path,
            "flow": flow,
            "env": env,
            "server": server,
            "project": project,
            "filename": filename,
            "last_modified": last_modified.strftime("%Y-%m-%d %H:%M:%S"),
            "size_gb": size_gb,
            "is_candidate": is_candidate
        })

    # Aplicar lógica por defecto: ordenar por fecha y preservar el más reciente por proyecto
    df = pd.DataFrame(inventory)
    if df.empty:
        return jsonify([])

    df['last_modified_dt'] = pd.to_datetime(df['last_modified'])
    df = df.sort_values(by=['project', 'last_modified_dt'], ascending=[True, False])

    processed_records = []
    for (project, flow), group in df.groupby(['project', 'flow']):
        for idx, row in group.iterrows():
            item = row.to_dict()
            del item['last_modified_dt']

            # Estado por persistencia
            if item['s3_path'] in persisted_states:
                item['status'] = persisted_states[item['s3_path']]
            else:
                # Regla por defecto: Más reciente = Preservado, resto = Descartado
                if idx == group.index[0]:
                    item['status'] = "Preservado"
                else:
                    item['status'] = "Descartado"

            processed_records.append(item)

    return jsonify(processed_records)


@app.route('/api/save-selection', methods=['POST'])
def save_selection():
    """Persiste los cambios de estado hechos por el usuario en las vistas."""
    payload = request.get_json() # Recibe lista de objetos {s3_path, status, ...}
    save_persisted_states(payload)
    return jsonify({"status": "success", "message": "Selección guardada correctamente."})


@app.route('/api/authorize-cleanup', methods=['POST'])
def authorize_cleanup():
    """
    Ejecuta la eliminación física en S3 para los elementos 'Descartados',
    guarda la persistencia final y retorna un reporte CSV para descarga automática.
    """
    payload = request.get_json() # Lista completa enviada desde el frontend
    s3_folder = get_s3_folder()
    
    deleted_items = []
    updated_persistence = []

    for item in payload:
        s3_path = item['s3_path']
        status = item['status']

        if status == "Descartado":
            try:
                # Eliminación en S3
                s3_folder.delete_path(s3_path)
                item['action_result'] = "ELIMINADO"
                item['error'] = ""
                deleted_items.append(item)
            except Exception as e:
                item['action_result'] = "ERROR"
                item['error'] = str(e)
                deleted_items.append(item)
        else:
            # Mantener conservados en persistencia
            updated_persistence.append({
                "s3_path": s3_path,
                "project": item['project'],
                "status": status,
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

    # Actualizar dataset administrado descartando los eliminados
    save_persisted_states(updated_persistence)

    # Generar reporte CSV para el cliente
    report_df = pd.DataFrame(deleted_items)
    output = io.BytesIO()
    report_df.to_csv(output, index=False, encoding='utf-8')
    output.seek(0)

    return send_file(
        output,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"reporte_limpieza_s3_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )