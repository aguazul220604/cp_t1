import dataiku
import dataikuapi
import pandas as pd
from flask import request, jsonify
from datetime import datetime, timedelta
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FECHA_LIMITE = datetime.now() - timedelta(days=120)

@app.route('/get_proyectos', methods=['GET'])
def get_proyectos():
    """Obtener las instancias del dataset y filtrar proyectos inactivos"""
    dataset = dataiku.Dataset("instances")
    df_instancias = dataset.get_dataframe()
    
    resultado = {}
    
    for _, row in df_instancias.iterrows():
        nombre_inst = row['nombre']
        url = row['url']
        api_key = row['api_key']
        
        try:
            client = dataikuapi.DSSClient(url, api_key)
            client._session.verify = False  
            
            proyectos = client.list_projects()
            proyectos_inactivos = []
            
            for p in proyectos:
                # Extraer la fecha de última modificación 
                last_mod_ms = p.get('lastModifiedOn', 0)
                if last_mod_ms > 0:
                    last_mod_date = datetime.fromtimestamp(last_mod_ms / 1000.0)
                else:
                    last_mod_date = datetime.min
                    
                if last_mod_date < FECHA_LIMITE:
                    proyectos_inactivos.append({
                        "id": p['projectKey'],
                        "nombre": p.get('name', p['projectKey']),
                        "ultima_mod": last_mod_date.strftime("%Y-%m-%d"),
                        "ultima_ejec": last_mod_date.strftime("%Y-%m-%d"), 
                        "jobs": 0, 
                        "usuarios": 0,
                        "escenarios": 0,
                        "actividad": [0, 0, 0, 0, 0] 
                    })
            
            if proyectos_inactivos:
                resultado[nombre_inst] = proyectos_inactivos
                
        except Exception as e:
            print(f"Error conectando a la instancia {nombre_inst}: {str(e)}")
            
    return jsonify(resultado)

@app.route('/ejecutar_limpieza', methods=['POST'])
def ejecutar_limpieza():
    """Recibe los proyectos no preservados y ejecuta la limpieza."""
    proyectos_a_limpiar = request.get_json()
    
    dataset = dataiku.Dataset("instances")
    df_instancias = dataset.get_dataframe()
    dict_instancias = {row['nombre']: {'url': row['url'], 'api_key': row['api_key']} for _, row in df_instancias.iterrows()}
    
    proyectos_borrados = 0
    
    for nombre_inst, lista_proyectos in proyectos_a_limpiar.items():
        if nombre_inst in dict_instancias:
            cred = dict_instancias[nombre_inst]
            try:
                client = dataikuapi.DSSClient(cred['url'], cred['api_key'])
                client._session.verify = False
                
                for p in lista_proyectos:
                    project = client.get_project(p['id'])
                    project.delete(
                        clear_managed_datasets=True, 
                        clear_output_managed_folders=True, 
                        clear_job_and_scenario_logs=True
                    )
                    proyectos_borrados += 1
            except Exception as e:
                print(f"Error limpiando en instancia {nombre_inst}: {str(e)}")
                
    return jsonify({"status": "ok", "total_procesados": proyectos_borrados})