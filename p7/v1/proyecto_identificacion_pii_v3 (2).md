# Proyecto: Identificación de PII en nombres de columna — v3

> **Documento guía de desarrollo (versión núcleo v0.4).** Esta versión se plantea como una solución nueva, construida desde cero. Los aprendizajes de las versiones anteriores se incorporan como _principios de diseño_ (sección 5), no como piezas heredadas del pipeline. Todo lo que no aporta de forma clara a las predicciones finales se dejó fuera o se marcó como opcional.

---

## 1. Objetivo

Dado **únicamente el nombre de una columna** de una tabla nueva, predecir:

1. si se trata de un dato PII (`pii`, `prob_pii`), y
2. de qué tipo de entidad se trata (`entity`, `prob_entity`).

## 2. Alcance y restricciones

| Aspecto | Decisión |
| --- | --- |
| Entrada en producción | Solo el nombre de la columna (`name`). Sin descripción, sin contenido de celdas. |
| Plataforma | Dataiku DSS (recipes Python, managed folders, webapp estándar). |
| LLMs | No disponibles en la instancia. Solo modelos clásicos de ML / NLP ligero. |
| Etiquetado de entidades | Manual por el etiquetador único del proyecto, sobre el dataset validado por Data Security. Sin dependencia de Data Security en el núcleo. |
| Fuera de alcance (v3 núcleo) | Verificación por contenido de celdas (ver sección 13, extensión futura) y active learning con el pool 267k (fase 5, aparcada). |

## 3. Contrato de inferencia

```
input:   column_name  (str)

output:  pii                     bool
         prob_pii                float [0, 1]
         entity                  str | null
         prob_entity             float [0, 1] | null
         -- campos auxiliares (explicabilidad y control) --
         nearest_validated_name  str
         similarity              float [0, 100]
         needs_review            bool
         label_source            str
```

Reglas del contrato:

- Si `pii = false` → `entity` y `prob_entity` son nulos.
- `prob_entity` es la probabilidad **condicionada** a que el campo sea PII: P(entidad | PII).
- Si `prob_entity` queda por debajo del umbral mínimo (`< 0.5` por defecto, a fijar en F4) → `entity = "REVISAR"`.
- `needs_review = true` cuando `similarity` con el catálogo validado es baja (`< 60` por defecto) o cuando `prob_pii` cae en la zona de incertidumbre (`thr ± 0.15`, thr elegido por F2 en F4).
- En el núcleo v3 `label_source = "gold_validado"` siempre. Los valores `manual_pool` / `pseudo` solo aplican si se activa la fase 5 (aparcada).

## 4. Datos

### 4.1 Dataset validado (gold) — Data Security

- Campos: `dataset`, `name`, `pii` (TRUE/FALSE), `target` (1/0).
- ~21k registros; desbalance ~96% NO PII / ~4% PII.
- No tiene `description` ni `type`.
- Contiene casos de nombres muy similares con etiquetas distintas (ej. `tel casa1` = TRUE; `tel casa ict1` = FALSE; `tel casa autenticado1` = FALSE).
- **Es la única fuente de verdad.** Toda evaluación se hace contra este dataset.
- Se le agregará la columna `entity` (etiquetado manual, sección 8).

### 4.2 Dataset no validado (pool) — Metadata Hub

- ~267k registros; ~44% NO PII / ~56% PII; etiquetas no validadas (con ruido).
- Campos: `dataset`, `name`, `type`, `description`, `pii`.
- **Rol en v3 núcleo:** aparcado (fase 5 no se ejecuta). A futuro: pool de candidatos para _active learning_. No se usa como fuente de etiquetas directas, ni como conjunto de evaluación.
- `description` y `type` se pueden consultar como **ayuda visual al etiquetar**, pero nunca son features del modelo.

### 4.3 Reglas de autoridad

1. Si un `name` está en el gold, su etiqueta prevalece sobre cualquier otra fuente.
2. La ausencia de un `name` en el gold **no** significa "no PII".
3. Ninguna etiqueta del pool entra al hold-out de evaluación.
4. Toda etiqueta nueva lleva su `label_source` (ver sección 9).

## 5. Principios de diseño (aprendizajes incorporados)

1. **Entrenar con lo que existe en inferencia.** Si producción solo recibe el nombre, el modelo solo usa el nombre. Queda prohibido usar `description` / `type` / `dataset` como features: fue la causa raíz de falsos negativos del modelo 267k y del parche de dimensiones (21151 vs 2386) en `pii_pyfunc_model.py`. El Feature Dropout no se usa en v3.
2. **La verdad validada manda, y se cuida.** Separar siempre lo validado de lo no validado; nunca mezclarlos en evaluación.
3. **Evitar fuga de información por casi-duplicados.** Variantes como `tel casa1`, `tel casa2` y `telcasa` deben caer del mismo lado de cualquier split (split por grupo).
4. **Desbalance como condición, no como sorpresa.** Ponderar clases y evaluar por clase, nunca solo con métricas globales.
5. **El costo de un falso negativo supera al de un falso positivo.** El threshold se elige con F2.
6. **Entidades definidas, no inferidas.** La taxonomía la define una persona con criterio de negocio; no emerge de un algoritmo de clustering.
7. **Pocas etapas, errores que no se propagan.** Evitar cadenas donde la salida de un modelo es la etiqueta de entrenamiento de otro.
8. **Probabilidades útiles.** Calibrar para que `prob_pii` y `prob_entity` signifiquen algo al aplicar thresholds.
9. **Normalización simple y determinista.** Minúsculas, separadores unificados y strip de sufijo numérico (`\d+$`). Sin diccionario `ROOTS` / `_split_roots` de `lib_pii_normalize.py`. Las variantes de escritura (`numcliente` vs `num cliente`) las absorben los n-gramas de carácter y el `group_id`, no un diccionario que haya que mantener. Cualquier heurística adicional solo entra si un experimento con GroupKFold muestra una mejora clara (por defecto: no se hace).
10. **Conocer los huecos de cobertura.** Hay dominios sin representación histórica en el gold (ej. corresponsalía bancaria/SWIFT y códigos de seguridad social); la taxonomía debe contemplarlos explícitamente con entidades dedicadas aunque tengan pocos ejemplos. El active learning queda aparcado.
11. **Cero dependencia de Data Security en el núcleo.** El etiquetado, la taxonomía y el piloto los ejecuta el etiquetador único del proyecto. Solo se reintroduce a Data Security si el piloto revela una discrepancia sistemática de criterio de negocio.

## 6. Arquitectura

```
                  ┌──────────────────────────────────────┐
 Gold 21k ──────► │ F0 Normalización simple + group_id   │
                  └──────────────┬───────────────────────┘
                                 ▼
                  ┌──────────────────────────────────────┐
                  │ F1 Taxonomía ligera → F2 Etiquetado   │
                  └──────────────┬───────────────────────┘
                                 ▼
                  ┌──────────────────────────────────────┐
                  │ F3 Split por grupo + baselines        │
                  └──────────────┬───────────────────────┘
                                 ▼
              ┌──────────────────┴──────────────────┐
              │ F4 Modelo A (PII)   Modelo B (entidad)│
              └──────────────────┬──────────────────┘
                                 ▼
                  F6 Inferencia + empaquetado
                                 ▼
                  F7 Evaluación y piloto  →  F8 Despliegue
```

> F5 (active learning con el pool 267k) y §13 (verificación por contenido) quedan **aparcadas** en el núcleo. Ruta única: F0 → F1 → F2 → F3 → F4 → F6 → F7. Solo se reactivan si F4 no cumple los criterios de la sección 10.

Dos modelos con responsabilidades separadas:

- **Modelo A — PII binario:** entrena con todo el gold. Produce `pii`, `prob_pii`.
- **Modelo B — Entidad:** entrena solo con registros PII=TRUE. Produce `entity`, `prob_entity`.

> **Decisión por validar en F4:** comparar contra un único modelo multiclase con `NO_PII` como una clase más. Si el multiclase iguala o supera a la combinación A+B, se prefiere por simplicidad.

## 7. Fases

> Formato de cada fase: objetivo, entregables, dependencias, pasos. Marca los pasos con `[x]` al completarlos.

> **Ruta única del núcleo:** F0 → F1 → F2 → F3 → F4 → F6 → F7. Con esta ruta ya existe un modelo funcional con el contrato completo. La F5 (active learning) y el pseudo-etiquetado quedan aparcados: solo se reactivan si F4 no alcanza los criterios de aceptación de la sección 10.

### 7.1 Puntos de contacto con Data Security (núcleo: ninguno)

En el núcleo no hay dependencia de Data Security (restricción de tiempo: un solo etiquetador):

1. ~~Sesión corta (30–60 min) en F1/F2~~ → la revisión de taxonomía y `REVISAR` la hace el etiquetador único (F1/F2).
2. ~~Piloto con Data Security (F7)~~ → el piloto lo ejecuta y revisa el etiquetador único, con comparativa contra el modelo previo.

Data Security solo se reintroduce si el piloto revela una discrepancia sistemática de criterio de negocio.

### F0 — Preparación y normalización

**Objetivo:** Dejar el gold limpio, normalizado y agrupado.
**Entregables:** `gold_catalog` con `name_light`, `name_norm`, `group_id`; dataset `f0_conflictos`; reporte de duplicados y conflictos.
**Depende de:** —

- [ ] Normalización ligera (`name_light`): minúsculas, sin acentos, trim, colapsa espacios. Conserva dígitos.
- [ ] Normalización sin sufijo (`name_norm`): además, eliminar el sufijo numérico final (`\d+$`). **Sin separación heurística de palabras pegadas (sin `ROOTS` / `_split_roots`).**
- [ ] Definir `group_id` = `name_norm` sin espacios, guiones ni guiones bajos (agrupa `numcliente` / `num cliente` / `num_cliente1`).
- [ ] Detectar `name_norm` con etiquetas PII contradictorias entre filas o datasets; listarlos en `f0_conflictos` (`name_norm, variantes, n_true, n_false, datasets, decision`) para resolución por el etiquetador único.
- [ ] Deduplicar para obtener el catálogo de nombres distintos y su conteo de filas.
- [ ] _(Opcional, por defecto NO hacer)_ Experimento corto: baseline con y sin separación heurística de palabras pegadas, con GroupKFold. Adoptarla solo si la mejora supera claramente el ruido.

### F1 — Taxonomía de entidades (ligera)

**Objetivo:** Definir el catálogo cerrado de entidades antes de etiquetar.
**Entregables:** `taxonomia_entidades` v1 (formato ligero, sección 8).
**Depende de:** F0

- [ ] Explorar los nombres PII distintos (ordenados por frecuencia) para proponer las entidades. Objetivo: 6–9 entidades + `NO_PII` / `REVISAR`.
- [ ] Para cada entidad: nombre, una línea de definición y 3–5 ejemplos. Nota de frontera solo donde haya confusión real.
- [ ] Incluir clases especiales: `NO_PII` y `REVISAR` (ambiguo). Evitar una clase "otros" abierta.
- [ ] Incluir entidades para los dominios con cobertura histórica nula (ej. SWIFT/corresponsalía), aunque tengan pocos ejemplos hoy.
- [ ] Mantener granularidad homogénea (no mezclar un concepto general con uno específico en el mismo nivel sin regla de desempate). Mínimo 10 `group_id` distintos por entidad para entrenarla; si no, fusionar o mandar a `REVISAR`.
- [ ] **Piloto de etiquetado:** con el borrador de taxonomía, el etiquetador único etiqueta una muestra de 100–150 nombres distintos. Ajustar entidades que se confunden, sobran o faltan, y recién entonces congelar la taxonomía.
- [ ] Congelar la taxonomía sin sesión con Data Security (restricción del núcleo).

### F2 — Etiquetado manual

**Objetivo:** Asignar `entity` a todo registro PII=TRUE del gold (etiquetador único, sin Data Security).
**Entregables:** Gold con columna `entity`; medida de consistencia propia.
**Depende de:** F1

- [ ] Exportar nombres PII=TRUE distintos por `name_norm` a un Editable Dataset (plantilla en sección 9).
- [ ] Etiquetar por `name_norm` y propagar a todas las variantes mediante join.
- [ ] Asignar `NO_PII` automáticamente a los registros PII=FALSE.
- [ ] Resolver los conflictos señalados en F0 (`f0_conflictos`; el gold gana; los nombres que sigan ambiguos van a `REVISAR`).
- [ ] **Chequeo de consistencia propia:** 3–5 días después, reetiquetar a ciegas una muestra (≥ 10% por entidad) y medir la concordancia con la primera pasada. Umbral: ≥ 0.85; si una entidad falla, ajustar su definición, fusionarla o mandarla a `REVISAR`.
- [ ] Revisar entidades con muy pocos ejemplos (< 10 `group_id`): fusionar o mover a `REVISAR` (fase 5 aparcada, no es vía de rescate en el núcleo).
- [ ] Congelar `gold_v1` (snapshot versionado) con `label_source = gold_validado`.

### F3 — Split y baselines

**Objetivo:** Preparar una evaluación confiable y un punto de referencia.
**Entregables:** Hold-out congelado; baseline reproducible; protocolo de validación cruzada.
**Depende de:** F2

- [ ] Hold-out de 15–20% **por `group_id`**, estratificado por entidad en lo posible. No se toca hasta F7.
- [ ] Como habrá pocos nombres PII distintos por entidad, el hold-out por sí solo dará métricas de entidad muy ruidosas. Reportar el F1 por entidad con las **predicciones out-of-fold de GroupKFold** (sobre todo el gold) además del hold-out, y no sobreinterpretar clases con menos de ~10 grupos en el hold-out.
- [ ] Definir GroupKFold (ej. 5 folds) sobre el resto, para selección de modelo.
- [ ] Baseline trivial: coincidencia exacta / vecino más cercano por similitud de carácter.
- [ ] Baseline lineal: TF-IDF de carácter + Regresión Logística.
- [ ] Registrar métricas base: recall PII, F1 PII, F1 por entidad.
- [ ] **Checkpoint:** revisar el baseline lineal con los criterios de la sección 10. Si ya los cumple, F4 se limita a calibrar y fijar thresholds; probar LightGBM solo si hace falta. La F5 no se activa en el núcleo.

### F4 — Modelado

**Objetivo:** Entrenar y seleccionar los modelos A (PII) y B (entidad).
**Entregables:** Modelos seleccionados y calibrados; reporte comparativo; thresholds.
**Depende de:** F3

**Features (solo nombre, lista cerrada):**
- TF-IDF de carácter (`char_wb`, n-gramas 2–4) sobre `name_norm`.
- Misma vectorización sobre el nombre sin espacios (robustez ante palabras pegadas).
- Opcionales: longitud, número de tokens, presencia de sufijo numérico.
- Prohibidos como features: `dataset`, `type`, `description` (no estarán disponibles o no son confiables en producción; solo se usan como contexto al etiquetar). Sin Feature Dropout.

**Pasos:**
- [ ] Comparar Regresión Logística, SVM lineal (calibrado) y LightGBM con GroupKFold.
- [ ] Aplicar pesos de clase (`class_weight` / `scale_pos_weight`) por desbalance PII y entre entidades.
- [ ] Evaluar variante multiclase única (`NO_PII` + entidades) contra A+B.
- [ ] Calibrar probabilidades (sigmoide o isotónica, obligatoria) y medir calibración (Brier / ECE).
- [ ] Seleccionar threshold de `prob_pii` con F2 sobre la curva precisión-recall (prioridad recall: el FN es más costoso que el FP).
- [ ] Definir umbral mínimo de `prob_entity` bajo el cual se emite `REVISAR` (por defecto `< 0.5`) y zona de `needs_review` (`thr ± 0.15`, `similarity < 60`).
- [ ] Guardar modelo seleccionado con su versión y métricas.

### F5 — Active learning con el pool (267k) [APARCADA en el núcleo]

**Objetivo:** Ampliar cobertura etiquetando solo lo más informativo del pool. No se ejecuta en el núcleo.
**Entregables:** Rondas de lotes etiquetados; `gold_v2`, `gold_v3`...; curva de mejora por ronda.
**Depende de:** F4. **Activación:** solo si F4 no cumple los criterios de la sección 10.

- [ ] Deduplicar y normalizar los nombres del pool; excluir los que ya están en el gold.
- [ ] Predecir sobre el pool con el modelo vigente y calcular similitud con el catálogo validado.
- [ ] Seleccionar el lote (200–300 nombres): baja similitud, alta incertidumbre, y muestreo de dominios sin cobertura.
- [ ] Etiquetar el lote (PII y entidad) por el equipo del proyecto, apoyándose en `description` y `dataset` como contexto.
- [ ] Añadir al entrenamiento con `label_source = manual_pool` y **peso menor** que el gold (tentativo, ej. 0.5; ajustar con el hold-out).
- [ ] Re-entrenar y re-evaluar **solo contra el hold-out validado**.
- [ ] Repetir 2–3 rondas; detener si la mejora marginal es insignificante.
- [ ] _(Opcional)_ Pseudo-etiquetado de predicciones de muy alta confianza con peso bajo; solo si mejora el hold-out.

### F6 — Inferencia y empaquetado

**Objetivo:** Encapsular el flujo completo en un componente reutilizable.
**Entregables:** Pipeline serializado + librería de normalización (`lib_pii_v3.py`) + función de inferencia con el contrato de la sección 3.
**Depende de:** F4 (núcleo; F5 solo si se reactiva)

- [ ] Empaquetar normalización + vectorizador + modelos en un solo `Pipeline`, guardado en un managed folder.
- [ ] Garantizar que entrenamiento e inferencia usan exactamente la misma función de normalización (misma librería).
- [ ] Implementar `predict(column_names) → DataFrame` con las columnas del contrato.
- [ ] Calcular `nearest_validated_name` y `similarity` contra el catálogo validado.
- [ ] Implementar la lógica de `needs_review` y de `REVISAR`.
- [ ] Pruebas unitarias con casos límite: nombres vacíos, solo dígitos, mayúsculas, caracteres especiales, nombres muy largos.

### F7 — Evaluación y piloto

**Objetivo:** Medir en el hold-out y validar con tablas reales.
**Entregables:** Reporte final de métricas; reporte de piloto; decisión de aceptación.
**Depende de:** F6

- [ ] Evaluar una sola vez sobre el hold-out congelado: recall y F1 de PII, F1 por entidad, matriz de confusión.
- [ ] Reportar recall de PII a precisión mínima fija y calibración.
- [ ] Seleccionar tablas reales nuevas (solo nombres de columna) no usadas en entrenamiento.
- [ ] Generar predicciones (`pii`, `prob_pii`, `entity`, `prob_entity`) y revisar una muestra con el etiquetador único (sin Data Security en el núcleo).
- [ ] Comparar contra versiones anteriores del modelo en las mismas tablas (acuerdo + top desacuerdos, mismo protocolo que `recipe_fase7_piloto.py`).
- [ ] Documentar discrepancias y decidir: ajuste de taxonomía, más etiquetado, o aceptación.

### F8 — Despliegue y monitoreo

**Objetivo:** Poner la solución en uso y mantenerla.
**Entregables:** Webapp / servicio en producción; plan de monitoreo.
**Depende de:** F7

- [ ] Exponer el modelo mediante webapp estándar de Dataiku (el usuario sube una tabla; se escanean los nombres de columna).
- [ ] Mostrar por columna: `pii`, `prob_pii`, `entity`, `prob_entity` y la marca de revisión.
- [ ] Registrar las predicciones y el feedback de revisores.
- [ ] Monitorear: distribución de `prob_pii`, proporción de `REVISAR`, caída de `similarity` promedio (deriva).
- [ ] Definir cadencia de re-entrenamiento con nuevas etiquetas.

## 8. Taxonomía de entidades (formato ligero)

A completar en F1:

| entidad | definición (1 línea) | ejemplos (3–5) | nota de frontera (solo si hay confusión real) |
| --- | --- | --- | --- |
| _por definir_ | | | |
| `NO_PII` | Campo que no es dato personal. | | |
| `REVISAR` | Nombre ambiguo; no se puede decidir solo con el nombre. | | |

Reglas para construirla:

- Granularidad homogénea (ver F1).
- Sin clases "cajón de sastre": lo ambiguo va a `REVISAR`.
- Mínimo de ejemplos por entidad para entrenar: ≥ 10 `group_id` distintos por clase; si no, fusionar o mandar a `REVISAR`.
- Cada entidad debe poder explicarse en una frase.
- Si más adelante se necesita una jerarquía (familias) o un mapeo a validadores de contenido, se agrega como columna sin tener que reetiquetar.

## 9. Plantilla de etiquetado

**Editable Dataset para F2:**

| Columna | Descripción |
| --- | --- |
| `name_norm` | Nombre normalizado (unidad de etiquetado). |
| `variantes` | Ejemplos de nombres originales que caen en este `name_norm`. |
| `datasets` | Datasets donde aparece (contexto, no feature). |
| `n_filas` | Frecuencia en el gold. |
| `entity_sugerida` | Sugerencia automática opcional, solo como ayuda. |
| `entity` | **Etiqueta final** (valor de la taxonomía). |
| `entity_recheck` | Segunda pasada a ciegas sobre la muestra de consistencia. |
| `notas` | Dudas o criterio aplicado. |

**Valores de `label_source` (propuestos):**

| label_source | Significado |
| --- | --- |
| `gold_validado` | Etiqueta PII validada por Data Security + entidad del etiquetador único. Único valor usado en el núcleo. |
| `manual_pool` | [APARCADO F5] Etiquetado manual del pool; peso menor, nunca al hold-out. |
| `pseudo` | [APARCADO F5] Pseudo-etiqueta del modelo; solo si se reactiva F5 y mejora el hold-out. |

## 10. Métricas y criterios de aceptación

| Métrica | Uso | Criterio de aceptación (núcleo) |
| --- | --- | --- |
| Recall PII | Principal (falsos negativos más costosos) | ≥ 0.88 en OOF + hold-out |
| Precisión PII | Evitar avalancha de falsos positivos | ≥ 0.40 a threshold F2 |
| F1 PII | Balance general | Reportar (no gate) |
| F2 PII | Selección de threshold de `prob_pii` | Maximizar sobre curva P-R |
| F1 por entidad | Calidad del clasificador de entidad | Reportar por clase; no sobreinterpretar clases con < 10 grupos en hold-out |
| Matriz de confusión entre entidades | Diagnóstico de fronteras en la taxonomía | Revisión cualitativa |
| Calibración (Brier / ECE) | Que las probabilidades sean interpretables | Reportar; Brier < 0.10 como referencia |
| Concordancia de etiquetado propio | Consistencia de la taxonomía | ≥ 0.85 por entidad, si no fusionar |
| % `REVISAR` / `needs_review` | Carga operativa (1 persona) | ≤ 25% |

> Referencia histórica: en una versión anterior el threshold de PII se fijó en 75% a mano sobre 105 columnas. En v3 se vuelve a elegir con F2 sobre el nuevo hold-out; defaults operativos: `prob_entity < 0.5 → REVISAR`, `needs_review si similarity < 60 o prob_pii en thr ± 0.15`.

## 11. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
| --- | --- | --- |
| Inconsistencia al etiquetar manualmente | Entidades ruidosas, techo bajo de calidad | Taxonomía con definición y ejemplos; chequeo de consistencia propia con reetiquetado a ciegas (≥ 0.85). |
| Etiquetador único sin Data Security | Sesgo personal, errores de criterio detectados tarde | Reglas de frontera en 1 línea por entidad; piloto con comparativa vs modelo previo; reintroducir DS solo ante discrepancia sistemática. |
| Entidades con muy pocos ejemplos | F1 inestable por clase | Fusionar / `REVISAR` (< 10 `group_id` no se entrena separado); F5 aparcada en el núcleo. |
| Fuga entre train y test por casi-duplicados | Métricas infladas | Split por `group_id`; hold-out congelado. |
| Dominios sin cobertura en el gold | Falsos negativos en producción | Entidades explícitas en la taxonomía; `needs_review` por baja similitud (`< 60`). |
| Etiquetas del pool no validadas | Contaminación del entrenamiento | F5 aparcada; si se reactiva: `label_source = manual_pool`, peso menor, nunca al hold-out. |
| Nombres ambiguos por naturaleza (ej. `numero`, `id`) | Predicciones poco fiables | Permitir `REVISAR`; reportar baja confianza; no forzar una entidad. |
| Diferencia entre normalización de entrenamiento e inferencia | Degradación silenciosa | Una sola librería compartida (`lib_pii_v3.py`); pruebas unitarias. |
| Deriva con nuevas convenciones de nombres | Pérdida de calidad con el tiempo | Monitoreo de similitud y de `prob_pii`; re-entrenamiento periódico. |

## 12. Artefactos propuestos en Dataiku

> Nombres propuestos; ajustar a los estándares del proyecto.

| Tipo | Nombre | Contenido |
| --- | --- | --- |
| Librería | `lib_pii_v3.py` | Normalización (`normalize_light/norm/group_id`), vectorización, `predict`. Reemplaza a `lib_pii_normalize.py` (sin `ROOTS`). |
| Dataset | `gold_catalog` | Gold normalizado y agrupado (F0). |
| Dataset | `f0_conflictos` | `name_norm` con PII contradictorio + decisión del etiquetador único (F0). |
| Dataset | `taxonomia_entidades` | Catálogo cerrado v1 (F1). |
| Dataset editable | `gold_entity_labeling` | Etiquetado manual por `name_norm` (F2). |
| Dataset | `gold_labeled_vN` | Gold con `entity` + `label_source`, versionado por snapshot (`gold_labeled_v1` en núcleo). |
| Dataset | `gold_holdout` / `gold_train` | Split por `group_id` (F3). |
| Dataset | `pool_names_distinct` | [APARCADO F5] Nombres distintos del 267k normalizados. |
| Dataset editable | `pool_labeling_round_N` | [APARCADO F5] Lotes de active learning. |
| Managed folder | `pii_v3_models` | Pipelines serializados y reportes de evaluación. |
| Dataset | `eval_report` | Métricas por fase / ronda. |

## 13. Extensión futura: verificación por contenido

Fuera del alcance del núcleo de v3:

- Se asociará a cada entidad un tipo de validador de contenido (por ejemplo, reconocedores ligeros por patrón), agregando esa columna a la taxonomía.
- A partir de la entidad predicha por nombre, se verificará sobre una muestra de valores de la columna que el contenido sea consistente con ella.
- Se compararán entidad por nombre y entidad por contenido para detectar falsos positivos y negativos, y se generará un veredicto por columna.

## 14. Decisiones abiertas / cerradas (núcleo v0.4)

Decididas en v0.4:
- [x] Alcance: solo núcleo F0–F4+F6–F7; F5 y §13 aparcadas.
- [x] Etiquetado: etiquetador único, 0 sesiones con Data Security en el núcleo.
- [x] Prioridad inferencia: recall-first, threshold por F2.
- [x] Features: solo `name` (`dataset/type/description` prohibidos); sin Feature Dropout.
- [x] Normalización: simple sin `ROOTS`; experimento de palabras pegadas por defecto NO.
- [x] Criterios §10 fijados; defaults `prob_entity < 0.5 → REVISAR`, `needs_review si similarity < 60 o prob_pii en thr ± 0.15`.

Abiertas (se cierran en su fase):
- [ ] Taxonomía v1: lista final de entidades (F1, 6–9 + NO_PII/REVISAR).
- [ ] Modelo A+B vs. multiclase único (F4).
- [ ] Algoritmo final: lineal (LR / SVM) vs. LightGBM (F4).
- [ ] Número de rondas, tamaño de lote y peso de las etiquetas del pool si se reactiva F5.
- [ ] ¿Pseudo-etiquetado? Solo si se reactiva F5 y mejora el hold-out.

## 15. Historial del documento

| Versión | Fecha | Cambios |
| --- | --- | --- |
| 0.1 | 2026-10-03 | Estructura inicial (hoja limpia). |
| 0.2 | 2026-10-03 | Versión mínima: sin heurística de palabras pegadas (experimento opcional), taxonomía ligera, revisiones con Data Security reducidas a dos puntos de contacto, chequeo de consistencia propia en lugar de segunda revisión externa, active learning sin validación externa por lote. |
| 0.3 | 2026-10-03 | Piloto de etiquetado en F1, ruta mínima viable, evaluación de entidades con predicciones out-of-fold y checkpoint tras el baseline. |
| 0.4 | 2026-10-03 | Núcleo único sin DS ni F5: etiquetador único, recall-first (F2), features solo `name`, normalización simple sin `ROOTS`, criterios §10 fijados, artefactos `f0_conflictos/taxonomia/lib_pii_v3`, F5/§13 aparcadas. |
