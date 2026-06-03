-- ============================================================================
-- PROYECTO: Jellyfish — Media Efficiency vs Spend (Looker Studio)
-- PLATAFORMA: Google BigQuery (SQL Estándar)
-- OBJETIVO: Recrear la vista `view_dashboard_ready` que alimenta el reporte de
--           Looker Studio. La vista enriquece la tabla cruda de marketing digital
--           con los campos calculados que consumen los tiles del dashboard.
--
-- CONTEXTO DEL ERROR ORIGINAL:
--   "Not found: Table gen-lang-client-0812859211:mkt_digital_raw.view_dashboard_ready
--    was not found in location US"
--   La vista dejó de existir (las tablas de un sandbox de BigQuery expiran a los
--   60 días). Este script la regenera. Ejecutar TODO en la región US.
--
-- PASOS:
--   1) Crear el dataset `mkt_digital_raw` en location US (si no existe).
--   2) Cargar `Jellyfish_mkt_digital_raw.csv` como tabla `mkt_digital_raw.mkt_digital`
--      (BigQuery > Crear tabla > Subir > CSV, con autodetección de esquema).
--   3) Ejecutar el CREATE OR REPLACE VIEW de abajo.
--   Como la vista conserva el nombre original, el dashboard de Looker Studio se
--   reconecta automáticamente sin tocar las fuentes de datos.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- (Opcional) Crear el dataset en US si aún no existe:
-- CREATE SCHEMA IF NOT EXISTS `gen-lang-client-0812859211.mkt_digital_raw`
--   OPTIONS (location = 'US');
-- ----------------------------------------------------------------------------


-- ----------------------------------------------------------------------------
-- VISTA: view_dashboard_ready
-- Limpieza: los nulos de métricas aditivas (Engagements, LinkClicks, VideoViews)
-- se normalizan a 0 con COALESCE para que las sumas y el Weighted Score sean
-- correctos. CPM usa SAFE_DIVIDE para evitar división por cero.
-- ----------------------------------------------------------------------------

-- IMPORTANTE: la vista conserva los nombres de columna ORIGINALES (Date, Spend,
-- Clicks, Weighted_Score, CPM…) porque los gráficos de Looker Studio están
-- enlazados a esos nombres exactos. Renombrarlos rompe los tiles.

CREATE OR REPLACE VIEW `gen-lang-client-0812859211.mkt_digital_raw.view_dashboard_ready` AS
SELECT
    -- Dimensiones (nombres originales)
    Date,
    FORMAT_DATE('%Y-%m', Date)               AS Month,
    Campaign_New,
    Canal                                    AS Channel,

    -- Métricas base (nulos -> 0)
    COALESCE(Spend, 0)                       AS Spend,
    COALESCE(Impressions, 0)                 AS Impressions,
    COALESCE(Clicks, 0)                      AS Clicks,
    COALESCE(Engagements, 0)                 AS Engagements,
    COALESCE(LinkClicks, 0)                  AS LinkClicks,
    COALESCE(VideoViews, 0)                  AS VideoViews,

    -- Weighted Score (fórmula del dashboard):
    -- = (Clicks x 1.0) + (Video Views x 0.1) + (Engagements x 0.5)
    COALESCE(Clicks, 0) * 1.0
      + COALESCE(VideoViews, 0) * 0.1
      + COALESCE(Engagements, 0) * 0.5        AS Weighted_Score,

    -- CPM = costo por mil impresiones. SAFE_DIVIDE protege contra 0 impresiones.
    SAFE_DIVIDE(COALESCE(Spend, 0), COALESCE(Impressions, 0)) * 1000
                                             AS CPM

FROM
    `gen-lang-client-0812859211.mkt_digital_raw.mkt_digital`;


-- ----------------------------------------------------------------------------
-- KPIs agregados (se calculan como métricas dentro de Looker Studio, no en la
-- vista). Referencia de cómo se obtienen los scorecards del header:
--
--   Total Spend       = SUM(spend)
--   Score             = SUM(weighted_score)
--   Efficiency Index  = SUM(weighted_score) / SUM(spend)
--   AVG CPM           = SUM(spend) / SUM(impressions) * 1000
-- ----------------------------------------------------------------------------

-- ----------------------------------------------------------------------------
-- (Opcional) Verificación rápida tras crear la vista — confirma que el dataset
-- es el correcto: Total Spend debe dar ~175.48M y AVG CPM ~8.8 para 2024.
-- ----------------------------------------------------------------------------
-- SELECT
--     ROUND(SUM(spend)/1e6, 2)                          AS total_spend_millones,
--     ROUND(SUM(weighted_score)/1e6, 1)                AS score_millones,
--     ROUND(SUM(weighted_score)/SUM(spend), 1)         AS efficiency_index,
--     ROUND(SUM(spend)/SUM(impressions)*1000, 1)       AS avg_cpm
-- FROM `gen-lang-client-0812859211.mkt_digital_raw.view_dashboard_ready`
-- WHERE EXTRACT(YEAR FROM Date) = 2024;

-- ============================================================================
-- FIN DEL SCRIPT
-- ============================================================================
