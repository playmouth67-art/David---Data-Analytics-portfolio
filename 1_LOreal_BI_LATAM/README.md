# Caso de Estudio — Plataforma BI L'Oréal LATAM (Beauty Sales Performance Intelligence)

**Autor:** David Adrián González Molina
**Tipo:** Plataforma de Business Intelligence completa (modelado + arquitectura + visualización)
**Stack:** Microsoft Power BI · Google BigQuery (GCP) · DAX · SQL · Row-Level Security

> **Aviso:** Proyecto de portafolio con fines demostrativos. Los datos son sintéticos, generados para el proyecto; no corresponden a información real de L'Oréal ni de ninguna empresa. La marca se usa únicamente como contexto de negocio simulado.

---

## Contexto y objetivo

Plataforma de BI que concentra el desempeño comercial de L'Oréal LATAM (México, Brasil, Argentina, Colombia y Chile) en una sola fuente: ventas sell-in / sell-out, market share y ROI de campañas. Las fuentes originales están fragmentadas (POS, distribuidores, e-commerce, medios); el modelo las consolida en un esquema gobernado donde el reporte que antes tomaba horas de armado manual se resuelve con consultas interactivas, y los usuarios de negocio pueden servirse solos.

El proyecto está orientado a arquitectura y modelado de datos, no solo a visualización.

## Arquitectura de datos

Patrón medallion (Bronze → Silver → Gold) alojado en BigQuery y consumido por Power BI:

- **Bronze (landing):** ingesta cruda append-only, particionada por fecha de carga.
- **Silver → Gold:** transformaciones SQL hacia marts en esquema estrella por dominio, con particionado y clustering para optimizar costo y rendimiento.
- **Capa semántica (Power BI):** datasets certificados, modelo estrella, librería central de medidas DAX y seguridad por fila.

## Modelo de datos

Esquema estrella sobre una tabla de hechos de 32,000 transacciones (2022–2024) y 5 dimensiones conformadas:

| Tabla | Rol | Detalle |
|---|---|---|
| `Fact_Sales` | Hechos | Cantidad, ingreso (USD y local), descuento, COGS, margen |
| `Dim_Product` | Dimensión | 40 SKUs · 4 divisiones (CPD, Luxe, Professional, Active Cosmetics) |
| `Dim_Geography` | Dimensión | 5 países LATAM con tipo de cambio a USD |
| `Dim_Channel` | Dimensión | 7 canales (Modern Trade, E-commerce, D2C, Professional…) |
| `Dim_Segment` | Dimensión | Segmentos de consumidor (Mass, Premium, Luxury, Pro…) |
| `Dim_Date` | Dimensión | Calendario completo, marcada como tabla de fecha para time intelligence |
| `Security_Mapping` | RLS | Mapeo dinámico email → país para Row-Level Security |

Decisiones de modelado: relaciones muchos-a-uno con filtro unidireccional, tabla de fecha única, todas las métricas en una tabla `_Measures` oculta, normalización de moneda a USD, y `DIVIDE()` en lugar del operador de división para manejar blancos sin errores. Incluye además una extensión snowflake (normalización de `Dim_Product` en marca / categoría / producto), justificada con un escenario de gestión de marcas.

## Seguridad y gobierno

Row-Level Security dinámico: cada usuario ve solo los datos de su país según el mapeo `email → CountryCode`, con roles regionales y globales de acceso ampliado. El gobierno de la plataforma incluye datasets certificados, etiquetas de sensibilidad en los datos financieros, modelo de acceso por workspace y un dashboard de salud y uso.

## Reportes construidos

1. **Executive Scorecard LATAM** — ingreso vs objetivo, deltas YoY, market share, top marcas, con drill-through por mercado.
2. **Brand Performance Workbook** — sell-out, gap sell-in vs sell-out, market share y ROI de campañas.
3. **Commercial Operational Dashboard** — operación e inventario (días de cobertura, OOS).
4. **Governance & Usage Dashboard** — salud de capacidad, adopción y calidad de datos.

## Calidad de datos

Scripts SQL en BigQuery para auditoría y limpieza: conteos de filas esperados por tabla, detección de duplicados por `transactionid`, validación de nulos e integridad referencial entre hechos y dimensiones.

## Qué demuestra este proyecto

Power BI avanzado (modelado estrella y snowflake, DAX con time intelligence, RLS dinámico, datasets certificados) y arquitectura medallion sobre BigQuery con particionado, clustering y refresco incremental. El SQL cubre transformación y auditoría de calidad. La parte de gobierno es la que menos se ve en portafolios: capacidad, sensibilidad, accesos y monitoreo de adopción, que es lo que separa un dashboard de una plataforma que una empresa puede operar. Del lado de negocio, el criterio para elegir los KPIs que un ejecutivo usa de verdad.

## Archivos del proyecto

- `LOreal.pbix` — reporte de Power BI.
- `LOrealLATAM_DataModel.xlsx` — dataset fuente con el esquema estrella completo.
- `loreal_latam_cleaning_queries.sql` — auditoría y limpieza en BigQuery.
- `loreal_snowflake_schema.sql` — extensión de normalización snowflake.
- `LATAM_BI_Platform_Project_Plan.docx` — blueprint de arquitectura de la plataforma.
- `LOrealLATAM_Theme.json` / `_Dark.json` — temas de marca para los reportes.
