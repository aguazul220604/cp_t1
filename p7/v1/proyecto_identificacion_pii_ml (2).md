# Proyecto: Identificación de Datos PII utilizando Machine Learning

## Objetivo

Crear un modelo de ML para evaluar los nombres de las columnas de nuevas tablas y predecir si se tratan de datos PII o no.

## Contexto

El proyecto consiste en el desarrollo de un modelo de ML utilizando la plataforma Dataiku con el propósito de detectar datos PII.

Previamente se realizó una consulta al Metadata Hub de la empresa (Banamex) para obtener distintos datasets de metadata, con un total de 4 fuentes de información. Dicha metadata contiene la información de distintas tablas, resaltando su dataset de origen, los nombres de sus columnas, la descripción de sus campos y su PII indicator. Esto resultó en un dataset final de 267k registros, con una proporción de aproximadamente 44% no PII y 56% PII.

Con esto se creó la variable `texto_completo` (Nombre + Descripción), con la cual se entrenó un modelo LightGBM para identificar PII en nuevas tablas evaluando el nombre de sus columnas — el modelo arrojaba la probabilidad de PII y el resultado de la inferencia (TRUE/FALSE).

Se obtuvo un buen resultado, pero surgieron dos inconvenientes:

1. Al haberse entrenado con `texto_completo` (nombre + descripción), en producción las tablas nuevas solo se evalúan por el nombre de sus columnas (sin descripción), lo que genera falsos negativos.
2. Los datos obtenidos del Metadata Hub no estaban del todo validados. Data Security proporcionó un nuevo dataset de 21K registros, validado.

## Consideraciones técnicas

El modelo actual (267k) genera `pii` y `prob_pii` en sus predicciones. La nueva versión busca que el modelo genere `pii`, `prob_pii` y `entity`.

El nuevo dataset (21k), aunque validado, tiene una proporción de 96% NO PII y 4% PII, y presenta casos donde nombres muy similares tienen etiquetas distintas, por ejemplo:

```
tel casa1              (true)
tel casa ict1           (false)
tel casa autenticado1   (false)
```

Además, el dataset de 21k no tiene el campo `description`.

## Estructura actual de los datasets

**dataset_no_validated_prepared (267k)**

- dataset
- name
- type
- description
- text (texto_completo = name + description)
- pii (TRUE/FALSE)
- target (1/0 según el campo pii)

**dataset_validated_prepared (21k)**

- dataset
- name
- pii (TRUE/FALSE)
- target (1/0 según el campo pii)

> **Regla de autoridad**: si `dataset_validated_prepared` (21k) tiene como FALSE un `name` que en `dataset_no_validated_prepared` (267k) está como TRUE (label noise), el 21k **siempre tiene la razón** — pero solo para lo que el 21k efectivamente cubre (ver Motor de Similitud más abajo). La ausencia de un `name` en el 21k no se interpreta como evidencia de "no PII".

## Estrategia de desarrollo

No existe un listado predefinido de entidades PII; deben extraerse del dataset de 21k a partir de la columna `name` (y tentativamente `dataset`), usando únicamente los registros clasificados como PII=TRUE.

**No se tiene acceso a LLMs en la instancia Dataiku.**

### 1. Clustering de entidades

Algoritmo: **Affinity Propagation** (no supervisado) — no requiere fijar `k` de antemano y entrega un exemplar representativo por clúster. Se aplica solo sobre los registros PII=TRUE del 21k.

**Vectorización — dos niveles distintos según el propósito:**

- **Para agrupar (clustering):** TF-IDF a nivel de **carácter** (n-gramas de 2 a 4 caracteres, `analyzer='char_wb'` en scikit-learn). Esto evita que variantes de escritura de una misma entidad (ej. `numcliente` vs. `num cliente`) terminen en clústeres distintos solo por diferir en espaciado o concatenación.
- **Para nombrar cada clúster** una vez formado: TF-IDF de **palabra** (bigramas), sobre el `name` normalizado (sufijos numéricos removidos vía regex, palabras pegadas separadas). Aquí se busca una etiqueta legible (ej. "tel", "numcliente"), no fragmentos de caracteres.

Ejemplo: si en el Clúster 4 los nombres son "tel casa1", "tel celular", "telefono ref", el algoritmo detecta que "tel" es el término dominante y nombra al clúster como entidad `tel`.

Resultado: el dataset de 21k queda con una nueva columna `Entity`.

### 2. Modelo Juez (LightGBM)

Entrenado únicamente con el 21k (ya con la columna `Entity` del paso anterior).

- **Input:** `name` (TF-IDF a nivel de carácter, para captar sutilezas como la diferencia entre "casa1" y "casa ict1").
- **Outputs:** `entity`, `prob_entity`.
- Usar `scale_pos_weight` por el desbalance 96/4 (de lo contrario el modelo predecirá que nada es PII).

**Nota de alcance:** el Modelo Juez **únicamente asigna entidad**. Nunca decide si un registro es PII o no — esa decisión recae por completo en el Motor de Similitud (ver siguiente sección). Esto evita que el desbalance y la cobertura limitada del 21k determinen directamente la clasificación PII del dataset completo.

### 3. Motor de Similitud (KNN + TF-IDF de carácter)

**Este es el mecanismo que decide `pii_final`.**

Se compara cada `name` distinto de `dataset_no_validated_prepared` (267k) contra el catálogo **completo** de `name` distintos de `dataset_validated_prepared` (21k) — incluyendo tanto PII=TRUE como PII=FALSE, no solo los positivos — usando TF-IDF de carácter (n-gramas 2-4, `char_wb`) y similitud coseno.

Pasos:

1. Deduplicar: extraer los `name` distintos del 267k y del 21k (reduce drásticamente el volumen de comparaciones).
2. Vectorizar ambos catálogos con el mismo TF-IDF de carácter.
3. Para cada `name` del 267k, encontrar su vecino más cercano en el 21k (similitud coseno) y obtener un `similarity_score` (0–100%).

### Regla de asignación de `pii_final`

| similarity_score                    | pii_final                                          | label_source              | sample_weight sugerido       |
| ----------------------------------- | -------------------------------------------------- | ------------------------- | ---------------------------- |
| ≥ 90% (incluye match exacto = 100%) | = etiqueta del vecino en el 21k                    | `validado_21k`            | 1.0                          |
| 50%–90%                             | = etiqueta del vecino en el 21k, con menor certeza | `evidencia_parcial`       | similarity_score normalizado |
| < 50%                               | = `pii` original del 267k (sin cambio)             | `sin_evidencia_mantenido` | 0.3 (tentativo)              |

> Los umbrales 90%/50% son punto de partida — se recomienda ajustarlos con una auditoría de cobertura (medir qué % de los `name` PII=TRUE del 267k caen en cada rango) antes de fijarlos en producción.

Para los registros donde `pii_final = TRUE`, se usa el Modelo Juez del paso 2 para asignar `entity` y `prob_entity`.

## Dataset enriquecido final

- dataset
- name
- type
- description
- pii _(identificador original)_
- entity
- prob_entity
- similarity_score
- label_source
- pii_final
- sample_weight
- has*description *(booleano; ~26% de description en el 267k está vacía)\_
- longitud _(en relación al campo name)_

## Feature importance

Orden propuesto (descendente) para el entrenamiento del modelo final:

- name
- pii_final
- longitud
- dataset (target encoding)
- type (los datos PII suelen ser string, no smallint por ejemplo)
- entity
- prob_entity

Variante segmentada, incluyendo descripción:

- name
- pii_final
- longitud
- dataset
- type
- entity
- prob_entity
- has_description
- description

Se utilizará **Feature Dropout** (o Data Augmentation) durante el entrenamiento, para obligar matemáticamente al LightGBM a no depender de `description` — de modo que en producción, al recibir tablas sin descripción, el modelo ya esté acostumbrado a predecir solo con el nombre.

## Flujo completo

1. **Clustering de entidades**: Affinity Propagation sobre los registros PII=TRUE del 21k. Agrupar con TF-IDF de carácter; nombrar cada clúster con TF-IDF de palabra normalizado → columna `Entity` en el 21k.

2. **Entrenar el Modelo Juez**: LightGBM sobre el 21k (ya con `Entity`), para predecir `entity` y `prob_entity` de cualquier nombre de columna.

3. **Ejecutar el Motor de Similitud**: comparar cada `name` distinto de `dataset_no_validated_prepared` (267k) contra el catálogo completo de `name` distintos de `dataset_validated_prepared` (21k). Asignar `pii_final` según la tabla de casos — donde exista match fuerte con el 21k, se hereda su etiqueta; donde no haya evidencia suficiente, se conserva la etiqueta original del 267k (no se asume no-PII por ausencia de evidencia). Para los registros con `pii_final = TRUE`, asignar `entity`/`prob_entity` con el Modelo Juez del paso 2. Registrar `label_source` y calcular `sample_weight`.

4. **Entrenar el modelo final**: usar el `dataset_no_validated_prepared` resultante (enriquecido) para entrenar el modelo LightGBM final — aplicando `sample_weight` según `label_source`, dando mayor importancia a `name`, y usando Feature Dropout sobre `description`. Caso de uso final: el usuario sube una tabla, se escanean los nombres de sus columnas, y por cada una se genera `pii`, `prob_pii` y `entity`.

## Fases del proyecto

> Nota: las Fases 1 y 3 pueden ejecutarse en paralelo una vez completada la Fase 0, ya que ambas dependen únicamente de ella.

### Fase 0 — Auditoría y preparación

**Objetivo:** Medir qué tan bien cubre el 21k los tipos de PII reales del 267k, antes de fijar ningún umbral.
**Entregables:** Reporte de cobertura (% de `name` PII=TRUE del 267k con evidencia fuerte/parcial/nula en el 21k); catálogos deduplicados y normalizados.
**Depende de:** —

**Pasos:**

1. Extraer los `name` distintos de `dataset_no_validated_prepared` (267k) y de `dataset_validated_prepared` (21k) (deduplicar).
2. Normalizar ambos catálogos: minúsculas, espacios sobrantes, eliminar sufijos numéricos al final del nombre (regex tipo `\d+$`), y separar palabras pegadas conocidas (heurística de raíces frecuentes: num, cliente, tel, cta, fec, etc.) para evitar mismatches como "numcliente" vs. "num cliente".
3. Vectorizar ambos catálogos normalizados con TF-IDF a nivel de carácter (n-gramas 2-4, `analyzer='char_wb'`).
4. Para cada `name` distinto PII=TRUE del 267k, calcular similitud coseno contra el catálogo completo del 21k y obtener el score del vecino más cercano (esto es un preview del Motor de Similitud, solo para medir cobertura).
5. Clasificar cada `name` en: cobertura fuerte (≥90%), parcial (50–90%) o nula (<50%).
6. Generar el reporte: % de `name` PII=TRUE del 267k en cada bucket, con ejemplos de "cobertura nula" para identificar qué tipos de entidad no están representados en el 21k (ej. fecha de nacimiento, dirección).
7. Con este reporte, decidir si los umbrales 90%/50% se mantienen o se ajustan, y si conviene solicitar a Data Security más ejemplos validados de las entidades con cobertura nula.

### Fase 1 — Extracción de entidades (clustering)

**Objetivo:** Agrupar los registros PII=TRUE del 21k (Affinity Propagation) y asignarles un nombre de entidad automático.
**Entregables:** Columna `Entity` en el 21k; catálogo de entidades encontradas (con revisión manual ligera).
**Depende de:** Fase 0

**Pasos:**

1. Filtrar `dataset_validated_prepared` (21k) por `pii = TRUE`.
2. Tomar los `name` ya normalizados (Fase 0) de estos registros.
3. Vectorizar con TF-IDF a nivel de carácter (n-gramas 2-4).
4. Calcular la matriz de similitud/afinidad (coseno) entre todos los pares.
5. Ejecutar Affinity Propagation sobre la matriz de afinidad (el parámetro `preference` controla el número de clústeres resultante; ajustar empíricamente).
6. Para cada clúster, tomar los `name` con espacios normalizados (sin la limpieza agresiva de sufijos) y calcular TF-IDF a nivel de **palabra** (bigramas).
7. Extraer el término/raíz con mayor score TF-IDF por clúster → esa es la etiqueta `Entity` del clúster.
8. Revisar manualmente (sanity check) los nombres de entidad generados — renombrar si el término dominante resulta poco claro para negocio.
9. Unir la columna `Entity` de vuelta a `dataset_validated_prepared` (21k) por `name`.

### Fase 2 — Modelo Juez

**Objetivo:** Entrenar el LightGBM que predice `entity`/`prob_entity` a partir del nombre de columna.
**Entregables:** Modelo Juez entrenado y validado (cross-validation, dado el tamaño reducido del 21k).
**Depende de:** Fase 1

**Pasos:**

1. Tomar `dataset_validated_prepared` (21k) con la columna `Entity` ya asignada.
2. Vectorizar `name` con TF-IDF a nivel de carácter (n-gramas 2-4) como input del modelo.
3. Definir el target: `Entity` (multiclase — LightGBM lo soporta de forma nativa).
4. Calcular los pesos de clase equivalentes a `scale_pos_weight` para compensar el desbalance 96/4 entre PII y no-PII, y el desbalance adicional entre entidades.
5. Dividir en train/validation con estratificación por `Entity`; dado el tamaño reducido, usar k-fold cross-validation (ej. 5 folds) en vez de un solo hold-out.
6. Entrenar el modelo LightGBM.
7. Evaluar con métricas por clase (F1 por entidad, no solo el promedio global), ya que hay clases de entidad con muy pocos ejemplos.
8. Guardar el modelo entrenado (Modelo Juez) para su uso en la Fase 3.

### Fase 3 — Motor de Similitud + pii_final

**Objetivo:** Calcular `similarity_score` entre 267k y 21k; aplicar la regla de `pii_final`/`label_source`/`sample_weight`.
**Entregables:** Dataset con `pii_final`, `label_source` y `sample_weight` asignados; umbrales 90%/50% ajustados con los resultados de la Fase 0.
**Depende de:** Fase 0

**Pasos:**

1. Tomar los catálogos deduplicados y normalizados de la Fase 0 (267k y 21k), reutilizando la vectorización TF-IDF de carácter ya calculada (o recalcular si cambió la normalización).
2. Para cada `name` distinto del 267k, calcular similitud coseno contra el catálogo **completo** del 21k (PII=TRUE y PII=FALSE) y obtener el vecino más cercano + su `similarity_score`.
3. Aplicar la regla de `pii_final` según la tabla de umbrales (ajustados en la Fase 0):
   - ≥90%: `pii_final` = etiqueta del vecino en 21k · `label_source` = `validado_21k` · `sample_weight` = 1.0
   - 50–90%: `pii_final` = etiqueta del vecino · `label_source` = `evidencia_parcial` · `sample_weight` = similarity_score normalizado
   - <50%: `pii_final` = `pii` original del 267k · `label_source` = `sin_evidencia_mantenido` · `sample_weight` = 0.3 (tentativo)
4. Propagar `pii_final`, `similarity_score`, `label_source` y `sample_weight` a nivel de fila del `dataset_no_validated_prepared` completo (267k), haciendo join por `name`.
5. Para los registros con `pii_final = TRUE`, usar el Modelo Juez (Fase 2) para predecir `entity` y `prob_entity`.
6. Para los registros con `pii_final = FALSE`, dejar `entity` y `prob_entity` como nulos/"N/A".

### Fase 4 — Dataset enriquecido

**Objetivo:** Unir todas las columnas derivadas en un único dataset de entrenamiento.
**Entregables:** `dataset_no_validated_prepared` enriquecido, listo para entrenamiento.
**Depende de:** Fases 2 y 3

**Pasos:**

1. Unir el dataset original con las columnas derivadas de la Fase 3 (`pii_final`, `similarity_score`, `label_source`, `sample_weight`, `entity`, `prob_entity`).
2. Calcular `has_description` (booleano: `description` no nula/no vacía).
3. Calcular `longitud` (longitud de caracteres de `name`).
4. Validar integridad: revisar que no haya nulos inesperados en `pii_final` o `sample_weight`.
5. Congelar esta versión del dataset como el conjunto de entrenamiento definitivo (versionarlo, ej. con un snapshot en Dataiku).

### Fase 5 — Entrenamiento del modelo final

**Objetivo:** Entrenar el LightGBM final con `sample_weight` y Feature Dropout sobre `description`.
**Entregables:** Modelo final entrenado (variante con y sin descripción segmentada).
**Depende de:** Fase 4

**Pasos:**

1. Definir dos variantes de features: (a) sin descripción (`name`, `pii_final`, `longitud`, `dataset`, `type`, `entity`, `prob_entity`) y (b) con descripción (agregando `has_description`, `description`).
2. Implementar Feature Dropout: durante el entrenamiento de la variante (b), enmascarar aleatoriamente `description`/`has_description` en una fracción configurable de las filas (ej. 50–70%) para simular la ausencia de descripción en producción.
3. Vectorizar/codificar features: TF-IDF (o similar) para `name` y `description`, target encoding para `dataset`, encoding categórico para `type`.
4. Entrenar LightGBM usando `sample_weight` (de la Fase 4) como peso por fila.
5. Ajustar hiperparámetros (`num_leaves`, `learning_rate`, etc.) con validación cruzada.
6. Comparar el desempeño de (a) y (b), evaluando específicamente el comportamiento cuando `description` está ausente (simular el escenario real de producción).
7. Seleccionar la variante final — probablemente la que incluye Feature Dropout, por su mejor generalización a datos sin descripción.

### Fase 6 — Evaluación y selección de threshold

**Objetivo:** Medir Recall/F1 y elegir el threshold de producción con F2-score.
**Entregables:** Threshold de producción definido y justificado.
**Depende de:** Fase 5

**Pasos:**

1. Evaluar el modelo final sobre un conjunto de validación/hold-out con Recall y F1 Score.
2. Generar la curva precision-recall variando el threshold de clasificación.
3. Calcular F2-score para cada punto de la curva.
4. Seleccionar el threshold que maximiza F2-score, o el que cumpla con un mínimo de precision aceptable para el negocio.
5. Documentar el threshold elegido y la justificación del trade-off precision/recall. (Se decidió 75%)

### Fase 7 — Validación piloto

**Objetivo:** Probar el modelo con tablas reales nuevas y revisar manualmente una muestra de predicciones, idealmente con Data Security.
**Entregables:** Reporte de validación piloto; ajustes finales si aplica.
**Depende de:** Fase 6

**Pasos:**

1. Seleccionar un conjunto de tablas reales nuevas (no usadas en entrenamiento) que representen el escenario real de producción (solo nombres de columna, sin descripción).
2. Correr el modelo final sobre estas tablas.
3. Generar un reporte de predicciones (`pii`, `prob_pii`, `entity`) por columna.
4. Revisar manualmente una muestra representativa de las predicciones, idealmente con la participación de Data Security.
5. Documentar discrepancias encontradas y decidir si requieren ajuste del modelo o del pipeline de `pii_final`.
6. Ajustar y re-entrenar si es necesario (loop breve con la Fase 5) (Se realizó una comparativa con las predicciones hechas por la versión anterior del modelo entrenada con los 267k y se obtuvieron mejorías)

### Fase 8 — Despliegue y monitoreo

**Objetivo:** Consumir el modelo final mediante una standard webapp Dataiku.
**Entregables:** Modelo en producción.
**Depende de:** Fase 7

**Pasos:**

1. Consumir la solución final (modelos).
2. Definir el contrato de entrada/salida (input: nombre de columna de tabla nueva; output: `pii`, `prob_pii`, `entity`, `prob_entity`).

## Métricas

- Recall y F1 Score para la evaluación general del modelo.
- F2-score para elegir el threshold final de clasificación (dado el desbalance de clases y el mayor costo de negocio de los falsos negativos frente a los falsos positivos).
