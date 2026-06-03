# Caso de Estudio — Promise & Speed (Mercado Libre · Supply & Logistics)

**Autor:** David Adrián González Molina
**Tipo:** Caso de negocio end-to-end de análisis de datos
**Stack:** Python (pandas) · SQL en Google BigQuery (GCP) · Tableau

> **Aviso:** Proyecto de portafolio con fines demostrativos. Los datos provienen de un caso de negocio y son **sintéticos / ficticios**; no corresponden a información operativa real de Mercado Libre ni de ninguna empresa.

---

## Contexto y problema de negocio

La tasa de conversión de compra (CVR) del Marketplace cayó de **70.3% (2023) a 66.5% (2024)**. El equipo de Inteligencia Logística necesitaba recuperarla mejorando el diseño de la promesa de entrega en la ruta más ofensora, **Zacatecas → Oaxaca** (16 horas de tránsito), minimizando tanto las entregas tardías como las anticipadas.

**Objetivo:** diseñar el horario de corte de venta ideal que ofrezca la mejor promesa de entrega manteniendo las entregas tardías por debajo del 4.5%, con hallazgos presentables a un VP en 30 minutos.

## Qué incluye el proyecto

| Archivo | Qué demuestra |
|---|---|
| `CasoNegocioPromiseSpeed Jun_25.xlsx` | Fuente de datos original (≈36,500 registros). |
| `meli-final-LIMPIO.ipynb` | **Python/pandas:** carga, estandarización, filtrado, auditoría de calidad y el análisis de KPIs de conversión y cumplimiento, con resultados ejecutados y comentarios explicativos. |
| `Consultas_PromiseSpeed_DavidG_LIMPIO.sql` | **SQL en Google BigQuery:** CVR por hora y SLA on-time mensual, con `SAFE_DIVIDE` y filtrado temprano para optimizar costo de consulta. |
| `das 1.twbx` | **Tableau:** dashboard de performance de entrega y conversión. |
| Presentación + PDF | Caso de negocio ejecutivo: hallazgos y recomendación. |

## Metodología (flujo de un analista de datos)

1. **Limpieza y gobernanza de datos** — estandarización de texto, filtrado a la ruta y año de interés, trabajo sobre una copia independiente del DataFrame.
2. **Auditoría de calidad** — verificación de duplicados y nulos. Se detectó que los nulos en la hora de entrega correspondían a cancelaciones (esperado), aislando además **15 registros anómalos** (sin entrega pero no cancelados) como evidencia de control de calidad.
3. **Análisis de KPIs** — CVR por hora de compra, % de entregas on-time por mes, y la "hora de oro" (mejor CVR con cero demoras).
4. **Replicación en SQL/BigQuery** — las mismas métricas calculadas sobre la tabla cargada como fuente única de verdad en un data warehouse en la nube.
5. **Visualización y storytelling** — dashboard en Tableau y presentación ejecutiva orientada a decisión.

## Hallazgos principales

- **CVR global de la ruta: 66.5%**, consistente con la caída que originó el caso.
- **Mejor hora de compra con cero demoras: 23:00 hrs (CVR ≈ 67.4%).**
- **El cuello de botella no es la lentitud:** las demoras (≈3.8%) ya estaban bajo el umbral de 4.5%; el problema real es que **≈49% de los envíos llegan anticipados**, señal de una promesa de entrega mal calibrada.
- **On-time mensual:** entre 36.7% (mayo, el peor) y 52.1% (julio, el mejor).

**Recomendación:** ajustar el horario de corte de venta para convertir entregas "anticipadas" en "on-time", alineando la promesa con la operación real de la ruta.

## Habilidades demostradas

- **Python para procesamiento y análisis de datos:** limpieza, transformación y EDA con pandas.
- **SQL avanzado en entorno cloud:** consultas analíticas en Google BigQuery (data warehouse en la nube), directamente transferible a entornos como Amazon Athena / Redshift.
- **ETL / preparación de datos:** pipeline de limpieza, auditoría de calidad e integridad de la información.
- **Visualización y BI:** dashboard en Tableau para seguimiento de KPIs.
- **Comunicación con stakeholders:** traducción de datos en una recomendación ejecutiva accionable.
