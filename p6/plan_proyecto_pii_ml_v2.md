# Plan de Proyecto PII ML v2 (2026-09-25)
Estado: Fase 0 hecha. Fase 1 en curso (vía Python). v1 intacta en `plan_proyecto_pii_ml.md`.

## 1. Origen e idea original

Proyecto Banamex / Dataiku para detectar datos PII desde Metadata Hub (4 fuentes de metadata de tablas).
Dataset inicial `dataset_no_validated_prepared` (267k, ~56% PII / 44% no PII).
Se creó `text = name + description` y se entrenó LightGBM v1 (hoy en `saved model`) que ante tablas nuevas evalúa solo el `name` de cada columna y devuelve PII (TRUE/FALSE) + probabilidad.

Dos inconvenientes detectados:
1. Mismatch train/inferencia: v1 se entrenó con `name + description` pero en producción solo hay `name` → falsos negativos.
2. Labels no validados: Data Security entregó `dataset_validated_prepared` (21k, ~96% no PII / 4% PII, sin `description`), con casos como `tel casa1 (true)` vs `tel casa ict1 / tel casa autenticado1 (false)`.

## 2. Datasets

| Dataset | N | Campos | Balance | Validado |
|---|---|---|---|---|
| `dataset_no_validated_prepared` | 267,615 | dataset, name, type, description, text (=name+description), pii, target | ~56% PII | No |
| `dataset_validated_prepared` | 21,000 | dataset, name, pii, target | ~4% PII | Sí (Data Security) |

Regla de gobierno: ante conflicto, el 21k siempre gana. `has_description` faltante en 267k ≈ 26%.

## 3. Decisiones acordadas (corrigen idea original)

| Idea original | Corrección v2 | Motivo |
|---|---|---|
| Un LightGBM da `Entity + Prob_Entity` y `PII_Validated = Prob_Entity>70%` | Dos cabezas: LGBM → `pii, prob_pii` / taxonomía → `entity, prob_entity` | `Prob_Entity` no es `Prob_PII`; `tel casa1` y `tel casa ict1` son mismo `TELEFONO` con distinto PII |
| `tel casa` como entidad final | Dos niveles: `base_entity` (`tel casa`, `numtel`) → `entity_type` (`TELEFONO, CUENTA, NOMBRE...`) | Lo pedido es tipo alto nivel; `numtel` y `tel casa1` → `TELEFONO` vía expansión de abreviaturas |
| `pii_final` como feature del modelo final | `pii_final` es **target limpio**, nunca input | En producción no existe; usarlo como feature es leakage |
| Threshold 70% fijo | Threshold de curva PR maximizando **F1** (reportar F2, PR-AUC) | Objetivo acordado: equilibrio P-R, no max-recall puro |
| Relabeleo automático del 267k | `pii_validated` como bandera + `discrepancia`, muestreo Checkpoint 2 → `pii_final` | El 21k tiene ~840 positivos y OOV alto; propagar sin revisión amplifica error |
| Split aleatorio | Split agrupado por `base_entity + dataset` | Fase 0 con recall 0.999 es leakage por variantes en train y test |
| `has_description` basta | + `description dropout` (ocultar description en 30-50% del train) y variantes (a)/(b) | Si no, el modelo sigue dependiendo de `description` |
| Target encoding `dataset` directo | OOF + fallback para datasets nuevos | Evita leakage y fallo en prod |

## 4. Arquitectura de inferencia final (solo `name`)

`name` → limpieza + expansión (`numtel→numero telefono`, `numcliente→numero cliente`, `fnacim→fecha nacimiento`) → [LightGBM PII, taxonomía regex+fuzzy] → `pii (0/1), prob_pii, entity, prob_entity, base_entity`.

No-PII (`sdo intvig, hora, pag iva`) → `entity=DESCONOCIDO, prob_entity=0.0`, correcto.

## 5. Taxonomía inicial (`fase1/entity_taxonomy.py`)

`TELEFONO, EMAIL, RFC, CURP, CUENTA (incl. numero cliente/instrumento), TARJETA, NOMBRE, DIRECCION, FECHA_NACIMIENTO, IDENTIFICADOR`, resto `DESCONOCIDO`. Regex ordenada específico→genérico sobre expandido + fuzzy fallback. Calificadores (`ict, autenticado, origen, servicio...`) no cambian entidad, solo señal PII.

## 6. Fases

### Fase 0 — hecha
Solo-`name` vs `name+description` sobre 267k. Resultado `name=0.999 / text=0.750` en recall se considera optimista por leakage (ver §3). Sirve de baseline, no de decisión final.

### Fase 1 — Binario PII 21k solo-`name` (en curso, `fase1/01_prepare.py, 02_train.py, 03_evaluate.py`)
In: 21k. Out: `modelo_fase1.joblib` + `pr_curve.csv`. Group-split 70/15/15, TF-IDF char_wb 3-5 + regex + fuzzy, `scale_pos_weight`, métricas PR-AUC/F1/F2. **Checkpoint 1:** F1 aceptable en hold-out y OOV 21k→267k ≤40%; si no, no avanzar.

### Fase 2 — Taxonomía (hecha base, `fase1/entity_taxonomy.py`)
Sin entrenamiento supervisado (no hay labels de entidad). Out: `entity, prob_entity`.

### Fase 3 — Enriquecer 267k (`fase1/04_score_267k.py`)
In: 267k + modelo Fase 1 + taxonomía. Out: `dataset_no_validated_enriquecido` con `name_clean, base_entity, entity, prob_entity, prob_pii_validated, pii_validated, discrepancia, threshold_aplicado`. No overwrite de `pii`. **Checkpoint 2:** muestreo `pii vs pii_validated` con Data Security → fijar `pii_final`.

### Fase 4 — Features final
Target=`pii_final`. Features: `name` (TF-IDF char + regex + fuzzy), `longitud`, `type`, `dataset-OOF`, `entity_type`, `has_description`, `description` con dropout. `pii_final` jamás como input.

### Fase 5 — Final LightGBM
(a) solo-name vs (b) con description-dropout. Métrica F1/PR-AUC en split agrupado. Gana la que no degrade sin `description`.

### Fase 6 — Validación negocio
Tablas reales nuevas solo-`name` vs baseline Fase 0. **Checkpoint 3:** muestreo Data Security antes de sustituir `saved model` v1.

## 7. Riesgos
Propagación 21k→267k (Chk 1-2); OOV (medir antes Fase 3); dependencia `description` (dropout + a/b); leakage `dataset` (OOF+fallback); threshold (F1, no fijo).

## 8. Entregables / Dataiku
F0 baseline; F1 `model_fase1` + métricas; F2 taxonomía; F3 enriquecido + reporte discrepancias; F4 dataset train; F5 final + comparativa; F6 reporte + aprobación. Datasets `dataset_21k_prepared`, `dataset_no_validated_enriquecido`; folder `model_fase1`; `saved model` v2.
