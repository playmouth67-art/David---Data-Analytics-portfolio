# Caso de Estudio — Promise & Speed (Mercado Libre · Supply & Logistics)

**Autor:** David Adrián González Molina
**Tipo:** Caso de negocio completo de análisis de datos
**Stack:** Python (pandas) · SQL en Google BigQuery (GCP) · Tableau

> **Aviso:** Proyecto de portafolio con fines demostrativos. Los datos provienen de un caso de negocio y son sintéticos; no corresponden a información operativa real de Mercado Libre ni de ninguna empresa.

---

## Contexto y problema de negocio

La tasa de conversión de compra (CVR) del Marketplace cayó de **70.3% (2023) a 66.5% (2024)**. El equipo de Inteligencia Logística necesitaba recuperarla mejorando el diseño de la promesa de entrega en la ruta más ofensora, **Zacatecas → Oaxaca** (16 horas de tránsito), sin disparar ni las entregas tardías ni las anticipadas.

**Objetivo:** diseñar el horario de corte de venta que ofrezca la mejor promesa de entrega manteniendo las entregas tardías por debajo del 4.5%, con hallazgos presentables a un VP en 30 minutos.

## Qué incluye el proyecto

| Archivo | Qué demuestra |
|---|---|
| `CasoNegocioPromiseSpeed Jun_25.xlsx` | Fuente de datos original (≈36,500 registros). |
| `meli-final-LIMPIO.ipynb` | Python/pandas: carga, estandarización, filtrado, auditoría de calidad y el análisis de KPIs de conversión y cumplimiento, con resultados ejecutados y comentarios. |
| `Consultas_PromiseSpeed_DavidG_LIMPIO.sql` | SQL en BigQuery: CVR por hora y SLA on-time mensual, con `SAFE_DIVIDE` y filtrado temprano para abaratar la consulta. |
| `das 1.twbx` | Tableau: dashboard de performance de entrega y conversión. |
| Presentación + PDF | Caso de negocio ejecutivo: hallazgos y recomendación. |

## Metodología

1. Limpieza: estandarización de texto, filtrado a la ruta y año de interés, trabajo sobre una copia independiente del DataFrame.
2. Auditoría de calidad: duplicados y nulos. Los nulos en la hora de entrega resultaron ser cancelaciones (esperado); quedaron aislados 15 registros anómalos, sin entrega pero no cancelados, como evidencia del control.
3. KPIs: CVR por hora de compra, % de entregas on-time por mes y la "hora de oro" (mejor CVR con cero demoras).
4. Réplica en SQL: las mismas métricas calculadas en BigQuery sobre la tabla cargada como fuente única del análisis.
5. Dashboard en Tableau y presentación ejecutiva.

## Hallazgos principales

- **CVR global de la ruta: 66.5%**, consistente con la caída que originó el caso.
- **Mejor hora de compra con cero demoras: 23:00 hrs (CVR ≈ 67.4%).**
- El cuello de botella no es la lentitud: las demoras (≈3.8%) ya estaban bajo el umbral de 4.5%. El problema real es que **≈49% de los envíos llegan anticipados** — la promesa de entrega está mal calibrada.
- **On-time mensual:** entre 36.7% (mayo, el peor) y 52.1% (julio, el mejor).

**Recomendación:** ajustar el horario de corte de venta para convertir entregas anticipadas en on-time, alineando la promesa con la operación real de la ruta.

## Qué demuestra este proyecto

Limpieza, transformación y EDA con pandas; SQL analítico en BigQuery (transferible a Athena o Redshift); un pipeline de preparación con su auditoría de calidad documentada; y el dashboard de KPIs en Tableau. La pieza menos común: todo termina en una recomendación concreta que un VP puede aprobar o rechazar en una junta, no en un notebook que nadie vuelve a abrir.
