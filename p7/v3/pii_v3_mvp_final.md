# Proyecto: Identificación de Datos PII (MVP)

## 1. Contexto y antecedentes

El proyecto busca desarrollar un modelo de Machine Learning en Dataiku para detectar datos personales (PII) en tablas nuevas.

Existía un prototipo entrenado con un dataset de 267k registros que usaba el nombre y la descripción de la columna. En producción, las tablas nuevas llegan únicamente con el nombre de la columna (sin descripción), lo que causaba fallos en el modelo original.

Ahora se cuenta con un dataset de 21k registros validado por Data Security (96% no PII / 4% PII). La estrategia a implementar:

- Descartar el dataset de 267k para cualquier tarea de entrenamiento, validación o calibración.
- Evitar depender de procesos externos (validaciones adicionales).
- Centrar exclusivamente en características extraídas del **nombre de la columna** en el dataset de 21k.

## 2. Objetivo

Crear un modelo de ML funcional trabajando en la plataforma Dataiku que prediga si una columna es PII y a qué entidad pertenece, generando `pii`, `prob_pii`, `entity` y `prob_entity`, evaluando únicamente el nombre de la columna.

## 3. Schemas de datasets (entrenamiento)

**Dataset inicial: `dataset_validated_prepared` (21k)**

| Columna   | Tipo / descripción   |
| --------- | -------------------- |
| `dataset` | Tabla de origen      |
| `name`    | Nombre de la columna |
| `pii`     | TRUE / FALSE         |
| `target`  | 1 / 0                |

**Dataset objetivo: `dataset_validated_labeled` (entregable tras el etiquetado)**

| Columna   | Tipo / descripción                                  |
| --------- | --------------------------------------------------- |
| `dataset` | Tabla de origen                                     |
| `name`    | Nombre de la columna                                |
| `pii`     | TRUE / FALSE                                        |
| `entity`  | Etiqueta asignada manualmente; vacía si `pii=FALSE` |

## 4. Formato de inferencia (salida de producción)

Por cada columna evaluada en una tabla nueva, el flujo devuelve:

| Campo         | Descripción                                 |
| ------------- | ------------------------------------------- |
| `tabla`       | Tabla evaluada                              |
| `columna`     | Nombre original de la columna               |
| `pii`         | Booleano                                    |
| `prob_pii`    | Probabilidad de ser PII                     |
| `entity`      | Clase de entidad; vacío si no es PII        |
| `prob_entity` | Confianza del modelo en la entidad asignada |

## 5. Modelos

El problema exige distinguir entre el dato en sí y sus metadatos (ej. `tel casa1` vs `tel casa ict1`), por lo que se usan dos modelos:

- **Modelo A (juez binario, detección de PII):** LightGBM entrenado con todo el dataset de 21k para predecir PII / no PII.
- **Modelo B (clasificador multiclase, asignación de entity):** LightGBM entrenado exclusivamente con los registros `pii=TRUE` del 21k. Su única función es predecir la entidad.

## 6. Fases y procedimiento

### Fase 1: Etiquetado manual rápido (21k)

1. Filtrar los registros `pii=TRUE` (~840 antes de deduplicar).
2. Asignar nombres de entidad descriptivos y simples (ej. `telefono`, `email`, `rfc`), usando siempre el mismo nombre para el mismo tipo de dato.
3. Agrupar bajo `otro_pii` cualquier entidad con menos de ~15 ejemplos distintos.
4. No se requiere taxonomía estricta: solo clasificar el tipo de dato.
5. Dejar `entity` vacío en todos los registros con `pii=FALSE`.

### Fase 2: Normalización y features

**Normalización:** minúsculas, separar camelCase y guiones bajos, y eliminar sufijos numéricos finales (ej. `tel casa1` → `tel casa`). El resultado es `name_norm`.

**Vectorización de texto** (solo a partir de `name_norm`):

- TF-IDF a nivel de caracteres: n-gramas de 2 a 5 con `char_wb`.
- TF-IDF a nivel de palabras: unigramas y bigramas.

### Fase 3: Entrenamiento y evaluación

1. Entrenar el Modelo A y el Modelo B.
2. **Validación cruzada agrupada** usando `name_norm` como grupo, para evitar fuga por nombres idénticos o hermanos repetidos.
3. En el Modelo A, ajustar `scale_pos_weight` para compensar el desbalance (96% vs 4%).
4. Regularizar LightGBM de forma conservadora (limitar `max_features` del TF-IDF, `min_child_samples` razonable, `colsample_bytree` y `reg_lambda`) dado el número reducido de positivos.
5. **Calibrar** las probabilidades de ambos modelos con regresión sigmoide (Platt) sobre predicciones out-of-fold. `scale_pos_weight` mejora el recall pero distorsiona las probabilidades, por lo que este paso es necesario para que `prob_pii` y `prob_entity` sean interpretables y para fijar el umbral con la curva de calibración.
6. **Métricas:**
   - Modelo A: PR-AUC, F1 y F2 (no usar Accuracy).
   - Modelo B: Macro-F1.
7. **Umbral del Modelo A:** elegirlo maximizando Recall (con F2 como guía) sobre las predicciones out-of-fold calibradas.

### Fase 4: Pipeline de inferencia (capa de catálogo + modelos)

Al recibir una tabla nueva, por cada columna:

1. **Modelo A:** Pasar el nombre por el Modelo A. Si la probabilidad supera el umbral, `pii=TRUE`.
2. **Modelo B:** Solo si `pii=TRUE`, obtener `entity` y `prob_entity`. Si `pii=FALSE`, dejar `entity` vacío.

## 7. Consideraciones técnicas críticas

- **Regla de oro:** el dataset de 267k (y sus etiquetas no validadas) está estrictamente prohibido para cualquier tarea de entrenamiento, validación o calibración. Todo el pipeline de ML depende del 21k.
- **Gestión del desbalance:** los falsos negativos tienen un alto costo para el negocio. El enfoque es maximizar el Recall y afinar el umbral con base en la curva de calibración del Modelo A.

## 8. Posibles mejoras posteriores

- Features de calificadores y `es_base`, y contexto de tabla (primera mejora si el modelo confunde dato con metadata).
- Regresión logística como baseline de comparación frente a LightGBM.
- Banda de revisión manual para predicciones inciertas.
- Diagnóstico con el 267k (solo inferencia) y lista de nombres inciertos para validación de Data Security.
- Taxonomía formal versionada.

## 9. Criterios de aceptación

- Modelos A y B entrenados solo con el 21k y evaluados con CV agrupado por `name_norm`.
- Probabilidades calibradas.
- Salida con el formato de la sección 4.
- Ningún dato del 267k usado en entrenamiento, validación ni calibración.
