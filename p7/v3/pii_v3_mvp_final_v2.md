# Proyecto: Identificación de Datos PII (MVP)

## 1. Contexto y antecedentes

El proyecto busca desarrollar un modelo de Machine Learning en Dataiku para detectar datos personales (PII) en tablas nuevas.

Existía un prototipo entrenado con un dataset de 267k registros que usaba el nombre y la descripción de la columna. En producción, las tablas nuevas llegan únicamente con el nombre de la columna (sin descripción), lo que causaba fallos en el modelo original.

Ahora se cuenta con un dataset de 21k registros validado por Data Security (95.6% no PII / 4.4% PII = 943 registros PII). La estrategia a implementar:

- Descartar el dataset de 267k para cualquier tarea de entrenamiento, validación o calibración. Única excepción permitida: minería léxica de la columna `name` (solo texto, sin etiquetas) para diseñar operadores de variación (ver Fase 2b).
- Evitar depender de procesos externos (validaciones adicionales).
- Centrar exclusivamente en características extraídas del **nombre de la columna** en el dataset de 21k.
- **Conservar las 23 entidades** observadas en whole-data para inferencia. `otro_pii` es la clase donde entra todo lo que no encaja en las demás clases pero sí es PII según el dataset de 21k.

Distribución whole-data PII (943):

| Grupo | Entidad (count) |
|---|---|
| Cabeza | cuenta 218, cliente 166, saldo 92, contrato 84, credito 74, telefono 67, direccion 61, tarjeta 51 |
| Media | nombre 25, fecha_nacimiento 17, rfc 17 |
| Cola (<15) | nomina 11, otro_pii 10, fecha_vencimiento 8, credenciales_id 7, apellido 6, sexo 6, datos_demograficos 6, documento_legal 4, correo 4, curp 4, nss 3, bienes_patrimonio 2 |

Nota: son conteos totales. Los `name_norm` distintos son aún menores (ej. `tel casa1..5 → tel casa`, `fnacim1..4 → fnacim`, `email1/2 → email`), por lo que la cola es el riesgo central del modelo B.

## 2. Objetivo

Crear un modelo de ML funcional en Dataiku que prediga si una columna es PII y a qué entidad pertenece (23 clases), generando `pii`, `prob_pii`, `entity` y `prob_entity`, evaluando únicamente el nombre de la columna.

## 3. Schemas de datasets (entrenamiento)

**Dataset inicial: `dataset_validated_prepared` (21k)**

| Columna | Tipo / descripción |
|---|---|
| `dataset` | Tabla de origen |
| `name` | Nombre de la columna |
| `pii` | TRUE / FALSE |
| `target` | 1 / 0 |

**Dataset objetivo: `dataset_validated_labeled` (entregable etiquetado, solo reales)**

| Columna | Tipo / descripción |
|---|---|
| `dataset` | Tabla de origen |
| `name` | Nombre de la columna |
| `pii` | TRUE / FALSE |
| `entity` | Una de las 23 entidades; vacía si `pii=FALSE`. `otro_pii` recoge todo PII que no encaja en las demás clases. |

**Dataset auxiliar (solo-train): `aug_train_only` (sintéticos)**

| Columna | Descripción |
|---|---|
| `name` | Nombre sintético generado |
| `entity` | Misma entidad del padre real |
| `is_synthetic` | Siempre 1 |
| `parent_norm` | `name_norm` real que lo originó (para agrupar fold) |

Ambos datasets reales + sintéticos nunca se mezclan en un CSV canónico. Los sintéticos existen solo para train.

## 4. Formato de inferencia (salida de producción)

Por cada columna evaluada en una tabla nueva, el flujo devuelve:

| Campo | Descripción |
|---|---|
| `tabla` | Tabla evaluada |
| `columna` | Nombre original de la columna |
| `pii` | Booleano |
| `prob_pii` | Probabilidad de ser PII (calibrada) |
| `entity` | Una de las 23 clases; vacío si no es PII |
| `prob_entity` | Confianza en la entidad asignada (calibrada) |

## 5. Modelos

El problema exige distinguir entre el dato en sí y sus metadatos (ej. `tel casa1` vs `tel casa ict1`), por lo que se usan dos modelos:

- **Modelo A (juez binario, detección de PII):** LightGBM entrenado con todo el dataset de 21k (reales + sintéticos solo en train) para predecir PII / no PII.
- **Modelo B (clasificador multiclase 23 clases, asignación de entity):** LightGBM entrenado exclusivamente con los registros `pii=TRUE` (reales + sintéticos solo en train). Su única función es predecir la entidad entre las 23 conservadas.

## 6. Fases y procedimiento

### Fase 1: Etiquetado manual (21k)

1. Filtrar los registros `pii=TRUE` (943).
2. Etiqueta `entity` con una de las 23 entidades. Nombres descriptivos y simples, consistentes.
3. Conservar como clases propias las entidades de cola (`nomina, fecha_vencimiento, credenciales_id, apellido, sexo, datos_demograficos, documento_legal, correo, curp, nss, bienes_patrimonio`). Todo PII sin encaje en ellas va a `otro_pii`.
4. Dejar `entity` vacío en todos los registros con `pii=FALSE`.
5. Resolver reubicaciones/pendientes antes de entrenar (ej. `clnt nbr → cliente`, `crd acct nbr → tarjeta/cuenta`, `num seg cli`, `numempdep`). Todo sintético posterior amplifica errores de etiqueta.

### Fase 2a: Normalización y features

**Normalización:** minúsculas, separar camelCase y guiones bajos, y eliminar sufijos numéricos finales (ej. `tel casa1` → `tel casa`). El resultado es `name_norm`.

**Vectorización de texto** (solo a partir de `name_norm`):

- TF-IDF a nivel de caracteres: n-gramas de 2 a 5 con `char_wb`.
- TF-IDF a nivel de palabras: unigramas y bigramas.

### Fase 2b: Minería léxica del 267k (solo texto, permitida)

1. Extraer únicamente la columna `name` del 267k. Ignorar por completo sus etiquetas.
2. Construir `variantes_lexicas_267k.csv`: separadores observados (`_/-/espacio/./sin_sep/camel/casing`), abreviaturas por familia (`correo/mail/e-mail, rfc/r.f.c./idfiscal, sexo/gndr, telefono/tel/cel/phone/ph/extn, direccion/addr/calle/colonia/cp/edo/cntry, cuenta/acct/cta, tarjeta/card/crd/plastico, nomina/numemp, cliente/clnt/cust`), calificadores (`titular_, cliente_, beneficiario_, _subc, _ordenante`).
3. Solo lo observado aquí puede usarse como operador de síntesis. Prohibido inventar raíces, traducir fuera del diccionario o usar labels del 267k.

### Fase 2c: Aumento sintético controlado (solo-train, cap parejo 30)

Objetivo: llevar cada entidad de cola a ~30 `name_norm` distintos. Déficit = `30 - n_distinto(name_norm)`. Estimado total ~280-300 filas (<1.5% del 21k).

- Tier 1 sin sintéticos: `cuenta, cliente, saldo, contrato, credito, telefono, direccion, tarjeta`.
- Tier 2 refuerzo ligero hasta 30: `nombre, fecha_nacimiento, rfc, nomina`.
- Tier 3 aumento completo hasta 30: `otro_pii, fecha_vencimiento, credenciales_id, apellido, sexo, datos_demograficos, documento_legal, correo, curp, nss, bienes_patrimonio`.

Operadores (preservan entidad, sin cruzar clases):
- `separadores/casing` (80% en regexables).
- `abreviatura ↔ expandido` solo si está en diccionario Fase 2b.
- `calificador tabla/contexto` (`titular_, cliente_`).
- Sufijos `1/2/A/B` en baja proporción (sirven al Modelo A; la normalización los borra para el Modelo B).
- 0 typos en `curp/rfc/nss/correo/sexo/fecha_*`.

Reglas: deduplicar por `name_norm` contra reales y entre sintéticos; todo hijo va al mismo fold que su `parent_norm`.

### Fase 3: Entrenamiento y evaluación

1. Entrenar el Modelo A (con sintéticos en train) y el Modelo B en ablation `B_base (solo reales)` vs `B_aug (reales + sintéticos en train)`.
2. **Validación cruzada agrupada** usando `name_norm` (extendido con `parent_norm` para sintéticos). Usar 3-fold para la cola (`bienes=2, nss=3` no admiten 5-fold).
3. En el Modelo A, ajustar `scale_pos_weight` para el desbalance (95.6% vs 4.4%).
4. Regularizar LightGBM de forma conservadora (limitar `max_features` del TF-IDF, `min_child_samples` razonable, `colsample_bytree` y `reg_lambda`).
5. **Calibrar** con regresión sigmoide (Platt) sobre predicciones out-of-fold **solo de filas reales**. Sintéticos excluidos de calibración y de elección de umbral.
6. **Métricas (solo sobre reales):**
   - Modelo A: PR-AUC, F1 y F2 (no usar Accuracy).
   - Modelo B: Macro-F1 + Recall por entidad de cola.
7. **Umbral del Modelo A:** maximizing Recall (F2 como guía) sobre OOF calibradas reales.
8. Decisión `B_base vs B_aug` por Macro-F1 real + Recall cola. Si una entidad de cola ni con 30 llega a Recall OOF ~0.5, no generar más: pasa a fallback regex en Fase 4.

### Fase 4: Pipeline de inferencia (capa de catálogo + modelos + reglas)

Al recibir una tabla nueva, por cada columna:

1. **Modelo A:** pasar el nombre. Si supera el umbral, `pii=TRUE`.
2. **Modelo B:** solo si `pii=TRUE`, obtener `entity` y `prob_entity`. Si `pii=FALSE`, `entity` vacío.
3. **Override por reglas:** si `prob_entity < umbral_OOF` y `regex.txt` matchea una única entidad (`curp/rfc/correo/sexo/fecha_nacimiento/fecha_vencimiento/nss/apellido/tarjeta/telefono/cuenta/...`), reemplazar por esa entidad. Si el regex es ambiguo, conservar salida ML. Esta capa es la garantía para la cola (`curp=4, correo=4, nss=3, bienes=2`).

## 7. Consideraciones técnicas críticas

- **Regla de oro:** el dataset de 267k (y sus etiquetas no validadas) está estrictamente prohibido para entrenamiento, validación o calibración. Única excepción: minería léxica de `name` sin etiquetas (Fase 2b).
- **Sintéticos nunca en val/test/calibración/reporte.** Solo train, marcados y agrupados por `parent_norm`.
- **Gestión del desbalance:** doble desbalance (95.6/4.4 global + 218:2 dentro de PII). Falsos negativos costosos: maximizar Recall en A; en B proteger la cola con cap parejo y fallback regex.
- **Riesgo residual:** los sintéticos dan robustez léxica, no señal nueva. La producción de la cola depende del override regex.

## 8. Posibles mejoras posteriores

- Features de calificadores y `es_base`, y contexto de tabla (si el modelo confunde dato con metadata).
- Regresión logística como baseline frente a LightGBM.
- Banda de revisión manual para predicciones inciertas (`prob` media).
- Diagnóstico con el 267k (solo inferencia) y lista de nombres inciertos para validación de Data Security.
- Taxonomía formal versionada (23 clases de este documento).

## 9. Criterios de aceptación

- 23 entidades conservadas en train y en inferencia; `otro_pii` recoge todo PII sin encaje en las demás clases.
- `dataset_validated_labeled` (reales) y `aug_train_only` (sintéticos) versionados por separado con `is_synthetic/parent_norm`.
- Modelos A y B entrenados solo con 21k (+ sintéticos solo-train) y evaluados con CV agrupado por `name_norm`.
- Ablation `B_base vs B_aug` reportada solo en reales.
- Probabilidades calibradas solo con OOF reales.
- Salida con el formato de la sección 4.
- Ningún dato/etiqueta del 267k usado en entrenamiento, validación ni calibración.
- Override regex operativo para la cola crítica.

## Apéndice A — Tabla de déficit (a recalcular con `name_norm` distintos)

`need = 30 - n_distinto(name_norm)`, floor 0. Estimado por totales: `nomina ~19, otro_pii ~20, fecha_venc ~22, credenciales ~23, apellido ~24, sexo ~24, datos_demo ~24, documento ~26, correo ~26, curp ~26, nss ~27, bienes ~28`.
