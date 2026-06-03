-- ============================================================
-- L'Oréal LATAM — Snowflake Schema Extension
-- Purpose: Split dim_product_clean into three normalised layers:
--   dim_brand        (brand grain)
--   dim_category     (category grain)
--   dim_product_slim (product grain — references brand + category)
-- Run each CREATE statement INDIVIDUALLY in BigQuery.
-- ============================================================


-- ============================================================
-- STEP 1 — Inspect what we have in dim_product_clean
-- (Run this first to understand the source columns)
-- ============================================================

SELECT
  product_id,
  product_name,
  brand,
  category,
  subcategory,
  division
FROM `loreal_latam.dim_product_clean`
LIMIT 20;


-- ============================================================
-- STEP 2 — CREATE dim_brand
-- One row per unique brand. Adds a synthetic brand_id key.
-- ============================================================

CREATE OR REPLACE TABLE `loreal_latam.dim_brand` AS
SELECT
  ROW_NUMBER() OVER (ORDER BY brand ASC)  AS brand_id,
  brand                                   AS brand_name,
  division,
  CASE
    WHEN UPPER(division) IN ('LUXE', 'LUXURY', 'PRESTIGE') THEN TRUE
    ELSE FALSE
  END                                      AS is_luxury,
  'L''Oréal Group'                         AS parent_company
FROM (
  SELECT DISTINCT brand, division
  FROM `loreal_latam.dim_product_clean`
  WHERE brand IS NOT NULL
)
ORDER BY brand_id;


-- Validate dim_brand
SELECT COUNT(*) AS brand_count FROM `loreal_latam.dim_brand`;
SELECT * FROM `loreal_latam.dim_brand` ORDER BY brand_id LIMIT 20;


-- ============================================================
-- STEP 3 — CREATE dim_category
-- One row per unique category + subcategory combination.
-- ============================================================

CREATE OR REPLACE TABLE `loreal_latam.dim_category` AS
SELECT
  ROW_NUMBER() OVER (ORDER BY category ASC, subcategory ASC)  AS category_id,
  category                                                      AS category_name,
  COALESCE(subcategory, category)                               AS subcategory_name,
  CASE
    WHEN LOWER(category) IN ('digital', 'ecommerce', 'online') THEN TRUE
    ELSE FALSE
  END                                                           AS is_digital_first
FROM (
  SELECT DISTINCT category, subcategory
  FROM `loreal_latam.dim_product_clean`
  WHERE category IS NOT NULL
)
ORDER BY category_id;


-- Validate dim_category
SELECT COUNT(*) AS category_count FROM `loreal_latam.dim_category`;
SELECT * FROM `loreal_latam.dim_category` ORDER BY category_id LIMIT 20;


-- ============================================================
-- STEP 4 — CREATE dim_product_slim
-- Product grain — references brand_id and category_id via JOIN.
-- This is the "hub" table in the snowflake spoke pattern.
-- ============================================================

CREATE OR REPLACE TABLE `loreal_latam.dim_product_slim` AS
SELECT
  p.product_id,
  p.product_name,
  b.brand_id,
  c.category_id,
  p.brand      AS brand_name_denorm,    -- kept for easy cross-check
  p.category   AS category_name_denorm  -- kept for easy cross-check
FROM `loreal_latam.dim_product_clean`  p
LEFT JOIN `loreal_latam.dim_brand`     b ON p.brand    = b.brand_name
LEFT JOIN `loreal_latam.dim_category`  c ON p.category = c.category_name
                                        AND COALESCE(p.subcategory, p.category) = c.subcategory_name;


-- Validate dim_product_slim — should match dim_product_clean row count
SELECT COUNT(*) AS product_slim_count FROM `loreal_latam.dim_product_slim`;

-- Check for orphaned products (no matching brand or category)
SELECT
  COUNT(*) AS orphan_count
FROM `loreal_latam.dim_product_slim`
WHERE brand_id IS NULL OR category_id IS NULL;

-- Preview join integrity
SELECT
  ps.product_id,
  ps.product_name,
  b.brand_name,
  b.division,
  b.is_luxury,
  c.category_name,
  c.subcategory_name
FROM `loreal_latam.dim_product_slim` ps
JOIN `loreal_latam.dim_brand`        b ON ps.brand_id    = b.brand_id
JOIN `loreal_latam.dim_category`     c ON ps.category_id = c.category_id
LIMIT 20;


-- ============================================================
-- STEP 5 — Verify the full snowflake chain
-- fact_sales_clean → dim_product_slim → dim_brand / dim_category
-- ============================================================

SELECT
  f.transaction_date,
  ps.product_name,
  b.brand_name,
  b.division,
  b.is_luxury,
  c.category_name,
  c.subcategory_name,
  f.revenue_usd,
  f.units_sold
FROM `loreal_latam.fact_sales_clean`  f
JOIN `loreal_latam.dim_product_slim`  ps ON f.product_id    = ps.product_id
JOIN `loreal_latam.dim_brand`          b ON ps.brand_id      = b.brand_id
JOIN `loreal_latam.dim_category`       c ON ps.category_id   = c.category_id
ORDER BY f.revenue_usd DESC
LIMIT 20;


-- ============================================================
-- STEP 6 — Revenue by Brand (snowflake path vs star path)
-- Run both queries and compare results — they should match.
-- ============================================================

-- Snowflake path (2 hops: fact → product_slim → brand)
SELECT
  b.brand_name,
  b.division,
  SUM(f.revenue_usd) AS total_revenue_snowflake
FROM `loreal_latam.fact_sales_clean`  f
JOIN `loreal_latam.dim_product_slim`  ps ON f.product_id = ps.product_id
JOIN `loreal_latam.dim_brand`          b ON ps.brand_id   = b.brand_id
GROUP BY b.brand_name, b.division
ORDER BY total_revenue_snowflake DESC;

-- Star path (1 hop: fact → dim_product_clean)
SELECT
  p.brand                 AS brand_name,
  p.division,
  SUM(f.revenue_usd)      AS total_revenue_star
FROM `loreal_latam.fact_sales_clean`  f
JOIN `loreal_latam.dim_product_clean` p ON f.product_id = p.product_id
GROUP BY p.brand, p.division
ORDER BY total_revenue_star DESC;
