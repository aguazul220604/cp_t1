# Plan de Proyecto: Identificación de Datos PII mediante Machine Learning

## 1. Contexto y Objetivo

Desarrollar un modelo (LightGBM) sobre Dataiku capaz de identificar si el **nombre de una columna** de una tabla corresponde a un dato PII, resolviendo dos problemas detectados en la primera versión:

1. **Mismatch entrenamiento/inferencia**: el modelo original se entrenó con `name + description`, pero en producción solo se dispone del `name`, generando falsos negativos.
2. **Calidad de los labels**: el dataset original (267k) no estaba validado por Data Security; existe un nuevo dataset validado (21k) que debe tratarse como fuente de verdad ante cualquier conflicto.

## 2. Datasets Disponibles

| Dataset | Registros | Campos | Balance PII | Validado |
|---|---|---|---|---|
| `dataset_no_validated_prepared` | 267,615 | dataset, name, type, description, text, pii, target | ~56% PII / 44% no PII | No |
| `dataset_validated_prepared` | 21,000 | dataset, name, pii, target | ~4% PII / 96% no PII | Sí (Data Security) |

**Regla de gobierno de datos:** ante discrepancia entre ambos datasets, `dataset_validated_prepared` tiene siempre prioridad (label noise en el 267k se corrige con el 21k, nunca al revés).

## 3. Problemática Central

- Las variantes de un mismo nombre base (`tel casa1` → PII, `tel casa ict1` → no PII) muestran que el modelo necesita distinguir **entidad base** de **sufijo/calificador**, no solo hacer bag-of-words.
- El 21k no tiene `description`, lo cual en realidad es una ventaja: refleja mejor el escenario real de producción.
- El 21k está fuertemente desbalanceado (4% positivos), por lo que su señal debe validarse con cuidado antes de usarse para etiquetar otros datos.

## 4. Correcciones Clave a la Estrategia Original

| Punto original | Ajuste propuesto | Motivo |
|---|---|---|
| Un solo modelo LightGBM que da "Entity" + "Prob_Entity" | Separar en dos pasos: (a) canonicalización de entidad (reglas/fuzzy/diccionario), (b) clasificación PII (LightGBM) | Un clasificador binario no produce una entidad canónica; mezclar ambos oculta errores |
| Relabeleo automático del 267k con el modelo del 21k | Usar la salida como **bandera de revisión**, no como sobrescritura automática, al menos en la primera iteración | Evita propagar errores del modelo chico (poca señal positiva) al dataset grande |
| Threshold de 70% fijo | Derivar el threshold de una curva Precision-Recall sobre un set de validación, optimizando para **recall** | El costo de un falso negativo (PII no detectado) es mayor que el de un falso positivo |
| `has_description` como único tratamiento de la ausencia de descripción | Agregar **description dropout**: ocultar `description` en una fracción del set de entrenamiento aunque exista | Fuerza al modelo a no depender de una columna que no existirá en producción |
| Target encoding de `dataset` sin más detalle | Usar encoding out-of-fold + valor de fallback para datasets nuevos no vistos | Evita leakage y falla en producción ante datasets desconocidos |
| Ir directo a construir el pipeline completo | Insertar un experimento de aislamiento (Fase 0) antes de construir nada | Permite medir cuánto del problema es "ruido de labels" vs. "falta de descripción" antes de invertir esfuerzo |

## 5. Fases del Proyecto

### Fase 0 — Experimento de Aislamiento (baseline)
**Objetivo:** entender qué proporción del problema es ruido de labels vs. ausencia de descripción.
- Entrenar un LightGBM usando *solo* `name` sobre `dataset_no_validated_prepared` (sin `description`).
- Comparar recall/precision/PR-AUC contra el modelo original (name+description).
- **Checkpoint 0:** decidir cuánto esfuerzo se destina a enriquecimiento (Fases 1-3) vs. simplemente reentrenar con description dropout (Fase 4).

### Fase 1 — Modelo de Clasificación PII sobre el 21k
**Objetivo:** un modelo confiable de PII (no de "entidad") entrenado solo con `name`.
- Split estratificado: hold-out de validación/test independiente del 21k (no usar el 100% para entrenar).
- Feature engineering: TF-IDF (chars), banderas regex, distancia fuzzy.
- Entrenamiento LightGBM con `scale_pos_weight` por el desbalance.
- Métricas: PR-AUC, recall y precision de la clase PII (no accuracy).
- **Checkpoint 1:** el modelo debe superar un recall mínimo definido (a acordar con Data Security) sobre el hold-out antes de usarse en la siguiente fase. Si no lo supera, no se avanza a enriquecer el 267k con sus salidas.

### Fase 2 — Canonicalización de Entidades (independiente del modelo PII)
**Objetivo:** obtener la entidad (`TELEFONO`, `CUENTA`, `NOMBRE`, etc.) + `prob_entity` a partir del `name`.
- Ningún dataset trae label de entidad: NO entrenar clasificador supervisado de entidad; usar taxonomía regex ordenada sobre nombre expandido (abreviaturas: `numtel`→`numero telefono`, `numcliente`→`numero cliente`, `fnacim`→`fecha nacimiento`) + fuzzy fallback (`fase1/entity_taxonomy.py`).
- `numtel` y `tel casa1` → misma entidad `TELEFONO` (distinta superficie, mismo tipo).
- `tel casa1` (PII) vs `tel casa ict1` (no PII) → misma entidad `TELEFONO`, distinto PII: la entidad NO decide el PII; los calificadores (`ict`, `autenticado`, `origen`, etc.) solo son señal para el binario.
- Salida final por columna nueva: `pii` (binario LightGBM), `prob_pii`, `entity`, `prob_entity`.

### Fase 3 — Enriquecimiento del Dataset 267k
**Objetivo:** generar un dataset enriquecido, con control de calidad.
- Aplicar el modelo de la Fase 1 (PII) y el mapeo de la Fase 2 (Entity) sobre `dataset_no_validated_prepared`.
- Agregar columnas: `entity`, `prob_entity`, `pii_validated`.
- **No sobrescribir automáticamente** el label `pii` original; generar `pii_final` como propuesta y marcar los casos de discrepancia alta para revisión (muestreo manual o revisión con Data Security).
- **Checkpoint 2:** revisar una muestra de discrepancias `pii` vs. `pii_validated` antes de fijar `pii_final` como ground truth definitivo.

### Fase 4 — Feature Engineering sobre el Dataset Enriquecido
- `has_description` (booleano).
- `longitud` (sobre `name`).
- `pii_final` (resultado validado del Checkpoint 2).
- **Description dropout**: en entrenamiento, ocultar `description` en una fracción de las filas que sí la tienen, para no sobre-depender de ella.
- Target encoding de `dataset` **out-of-fold**, con valor de fallback para datasets no vistos.

### Fase 5 — Entrenamiento del Modelo Final
- Entrenar LightGBM sobre el dataset enriquecido de 267k, con el orden de importancia propuesto:
  `name → pii_final → longitud → dataset (encoded) → type → entity → prob_entity → has_description → description (con dropout)`
- Entrenar y evaluar dos variantes: (a) solo `name`-based features, (b) incluyendo `description` con dropout, para confirmar que (b) no degrada el desempeño cuando falta `description`.

### Fase 6 — Evaluación Final y Validación de Negocio
- Evaluar el modelo final sobre un conjunto de tablas reales nuevas (solo `name`, como en producción).
- Comparar contra el baseline de Fase 0.
- **Checkpoint 3:** validar con Data Security una muestra de las predicciones antes de considerar el modelo listo para uso operativo.

## 6. Riesgos y Mitigaciones

| Riesgo | Mitigación |
|---|---|
| Propagación de error del modelo 21k hacia el 267k | Checkpoint 1 y 2; revisión de discrepancias antes de fijar `pii_final` |
| Baja cobertura de vocabulario del 21k frente al 267k | Medir overlap de entidades/vocabulario entre datasets antes de la Fase 3 |
| Modelo final sigue dependiendo implícitamente de `description` | Description dropout + comparación explícita de variantes (a) y (b) en Fase 5 |
| Leakage por target encoding de `dataset` | Encoding out-of-fold + fallback definido |
| Threshold subóptimo para el caso de uso (compliance) | Derivar threshold de curva PR optimizando recall, no valor fijo |

## 7. Entregables por Fase

- **Fase 0:** métricas comparativas baseline (name-only) vs. modelo original.
- **Fase 1:** modelo PII (21k) + métricas en hold-out.
- **Fase 2:** diccionario/reglas de canonicalización de entidades.
- **Fase 3:** `dataset_no_validated_enriquecido` + reporte de discrepancias revisadas.
- **Fase 4:** dataset final de entrenamiento con features definidas.
- **Fase 5:** modelo LightGBM final + comparación de variantes con/sin description dropout.
- **Fase 6:** reporte de validación sobre tablas reales + aprobación de Data Security.
