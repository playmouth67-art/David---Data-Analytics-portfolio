# Caso de Estudio — Plataforma BI L'Oréal LATAM (Beauty Sales Performance Intelligence)

**Autor:** David Adrián González Molina
**Tipo:** Plataforma de Business Intelligence end-to-end (modelado + arquitectura + visualización)
**Stack:** Microsoft Power BI · Google BigQuery (GCP) · DAX · SQL · Row-Level Security

> **Aviso:** Proyecto de portafolio con fines demostrativos. Los datos son **sintéticos / ficticios**, generados para el proyecto; no corresponden a información real de L'Oréal ni de ninguna empresa. La marca se usa únicamente como contexto de negocio simulado.

---

## Contexto y objetivo

Plataforma de BI diseñada como **única fuente de verdad** para el desempeño comercial de L'Oréal LATAM (México, Brasil, Argentina, Colombia y Chile): ventas (sell-in / sell-out), market share y ROI de campañas. El objetivo es consolidar fuentes fragmentadas (POS, distribuidores, e-commerce, medios) en un modelo gobernado que reduzca el tiempo de generación de reportes de horas manuales a consultas interactivas, habilitando self-service para usuarios de negocio.

Es un proyecto orientado a **arquitectura y modelado de datos**, no solo a visualización.

## Arquitectura de datos

Sigue un patrón **medallion** (Bronze → Silver → Gold) alojado en BigQuery y consumido por Power BI:

- **Bronze (landing):** ingesta cruda append-only, particionada por fecha de carga.
- **Silver → Gold:** transformaciones SQL hacia marts en esquema estrella por dominio, con particionado y clustering para optimizar costo y rendimiento.
- **Capa semántica (Power BI):** datasets certificados, modelo estrella, librería central de medidas DAX y seguridad por fila.

## Modelo de datos

Esquema estrella sobre una tabla de hechos de **32,000 transacciones** (2022–2024) y 5 dimensiones conformadas:

| Tabla | Rol | Detalle |
|---|---|---|
| `Fact_Sales` | Hechos | Cantidad, ingreso (USD y local), descuento, COGS, margen |
| `Dim_Product` | Dimensión | 40 SKUs · 4 divisiones (CPD, Luxe, Professional, Active Cosmetics) |
| `Dim_Geography` | Dimensión | 5 países LATAM con tipo de cambio a USD |
| `Dim_Channel` | Dimensión | 7 canales (Modern Trade, E-commerce, D2C, Professional…) |
| `Dim_Segment` | Dimensión | Segmentos de consumidor (Mass, Premium, Luxury, Pro…) |
| `Dim_Date` | Dimensión | Calendario completo, marcada como tabla de fecha para time intelligence |
| `Security_Mapping` | RLS | Mapeo dinámico email → país para Row-Level Security |

**Decisiones de modelado clave:** relaciones muchos-a-uno con filtro unidireccional, tabla de fecha única, todas las métricas en una tabla `_Measures` oculta, normalización de moneda a USD, y `DIVIDE()` en lugar del operador de división para manejo seguro de blancos. Se incluye además una **extensión snowflake** (normalización de `Dim_Product` en marca/categoría/producto) justificada por un escenario de negocio real de gestión de marcas.

## Seguridad y gobierno

- **Row-Level Security dinámico:** cada usuario ve solo los datos de su país según el mapeo `email → CountryCode`; roles regionales y globales con acceso ampliado.
- **Gobierno de plataforma:** datasets certificados, etiquetas de sensibilidad en datos financieros, modelo de acceso por workspace y dashboard de salud/uso de la plataforma.

## Reportes construidos

1. **Executive Scorecard LATAM** — ingreso vs objetivo, deltas YoY, market share, top marcas, con drill-through por mercado.
2. **Brand Performance Workbook** — sell-out, gap sell-in vs sell-out, market share y ROI de campañas.
3. **Commercial Operational Dashboard** — operación e inventario (días de cobertura, OOS).
4. **Governance & Usage Dashboard** — salud de capacidad, adopción y calidad de datos.

## Calidad de datos

Scripts SQL en BigQuery para auditoría y limpieza: conteos de filas esperados por tabla, detección de duplicados por `transactionid`, validación de nulos e integridad referencial entre hechos y dimensiones.

## Habilidades demostradas

- **Power BI avanzado:** modelado estrella/snowflake, medidas DAX con time intelligence, RLS dinámico, datasets certificados.
- **Arquitectura de datos en la nube:** patrón medallion ETL/ELT sobre GCP BigQuery, particionado, clustering y refresco incremental.
- **SQL analítico:** transformaciones, auditoría de calidad e integridad de datos.
- **Gobierno de BI a escala:** capacidad, sensibilidad, modelo de acceso y monitoreo de adopción.
- **Visión de negocio:** traducción de datos comerciales en KPIs accionables para stakeholders ejecutivos.

## Archivos del proyecto

- `LOreal.pbix` — reporte de Power BI.
- `LOrealLATAM_DataModel.xlsx` — dataset fuente con el esquema estrella completo.
- `loreal_latam_cleaning_queries.sql` — auditoría y limpieza en BigQuery.
- `loreal_snowflake_schema.sql` — extensión de normalización snowflake.
- `LATAM_BI_Platform_Project_Plan.docx` — blueprint de arquitectura de la plataforma.
- `LOrealLATAM_Theme.json` / `_Dark.json` — temas de marca para los reportes.
