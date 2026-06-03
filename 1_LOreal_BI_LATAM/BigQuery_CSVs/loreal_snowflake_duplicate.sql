-- ============================================================
-- L'Oréal LATAM — Snowflake Schema: Duplicate + Extend
--
-- PURPOSE: Duplicate the loreal_latam dataset into a new dataset
--   called loreal_latam_snowflake, then normalise dim_product_clean
--   into three tables: dim_brand, dim_category, dim_product_slim.
--
-- BUSINESS SCENARIO (justification for snowflake):
--   The L'Oréal LATAM CMO Office has requested that brand-level
--   attributes — brand tier, sustainability score, digital priority
--   flag, and parent brand — be added to the BI platform. These
--   attributes are managed centrally by the Brand Architecture team
--   and change independently of individual products. In the current
--   star schema (dim_product_clean), updating a brand's tier would
--   require touching every product row for that brand — hundreds of
--   rows per brand, each time tier changes during annual reviews.
--   Normalising into dim_brand allows a single-row update per brand,
--   supports a separate Brand Management feed, and enables brand-level
--   KPIs (Total Revenue by Brand Tier, Sustainability Score vs Revenue)
--   that are impossible in the flat schema.
--
-- HOW TO RUN:
--   Run each numbered block INDIVIDUALLY. Do NOT batch-execute.
--   After each CREATE, run the validation SELECT before moving on.
-- ============================================================


-- ============================================================
-- STEP 0 — Create the new dataset manually in BigQuery UI
-- ============================================================
-- In BigQuery Console:
--   1. Click the 3-dot menu next to your project
--   2. Select "Create dataset"
--   3. Dataset ID: loreal_latam_snowflake
--   4. Location: same region as loreal_latam (e.g., US)
--   5. Click Create
--
-- Then come back here and run the steps below.


-- ============================================================
-- STEP 1 — Copy fact_sales_clean
-- ============================================================

CREATE OR REPLACE TABLE `loreal_latam_snowflake.fact_sales_clean` AS
SELECT * FROM `loreal_latam.fact_sales_clean`;

-- Validate
SELECT
  COUNT(*)       AS row_count,
  MIN(transaction_date) AS earliest_date,
  MAX(transaction_date) AS latest_date,
  ROUND(SUM(revenue_usd), 2) AS total_revenue
FROM `loreal_latam_snowflake.fact_sales_clean`;


-- ============================================================
-- STEP 2 — Copy dim_geography_clean
-- ============================================================

CREATE OR REPLACE TABLE `loreal_latam_snowflake.dim_geography_clean` AS
SELECT * FROM `loreal_latam.dim_geography_clean`;

SELECT COUNT(*) AS geo_rows FROM `loreal_latam_snowflake.dim_geography_clean`;


-- ============================================================
-- STEP 3 — Copy dim_channel_clean
-- ============================================================

CREATE OR REPLACE TABLE `loreal_latam_snowflake.dim_channel_clean` AS
SELECT * FROM `loreal_latam.dim_channel_clean`;

SELECT COUNT(*) AS channel_rows FROM `loreal_latam_snowflake.dim_channel_clean`;


-- ============================================================
-- STEP 4 — Copy dim_segment_clean
-- ============================================================

CREATE OR REPLACE TABLE `loreal_latam_snowflake.dim_segment_clean` AS
SELECT * FROM `loreal_latam.dim_segment_clean`;

SELECT COUNT(*) AS segment_rows FROM `loreal_latam_snowflake.dim_segment_clean`;


-- ============================================================
-- STEP 5 — Copy dim_date
-- ============================================================

CREATE OR REPLACE TABLE `loreal_latam_snowflake.dim_date` AS
SELECT * FROM `loreal_latam.dim_date`;

SELECT COUNT(*) AS date_rows FROM `loreal_latam_snowflake.dim_date`;


-- ============================================================
-- STEP 6 — Copy security_mapping_clean
-- ============================================================

CREATE OR REPLACE TABLE `loreal_latam_snowflake.security_mapping_clean` AS
SELECT * FROM `loreal_latam.security_mapping_clean`;

SELECT COUNT(*) AS security_rows FROM `loreal_latam_snowflake.security_mapping_clean`;


-- ============================================================
-- STEP 7 — Inspect dim_product_clean from source
--   (understand what we are normalising before we touch anything)
-- ============================================================

SELECT
  product_id,
  product_name,
  brand,
  category,
  subcategory,
  division
FROM `loreal_latam.dim_product_clean`
ORDER BY brand, category
LIMIT 30;

-- Distinct brands and divisions
SELECT
  brand,
  division,
  COUNT(*) AS product_count
FROM `loreal_latam.dim_product_clean`
GROUP BY brand, division
ORDER BY brand;

-- Distinct categories and subcategories
SELECT
  category,
  subcategory,
  COUNT(*) AS product_count
FROM `loreal_latam.dim_product_clean`
GROUP BY category, subcategory
ORDER BY category, subcategory;


-- ============================================================
-- STEP 8 — CREATE dim_brand (normalised brand layer)
--
-- New columns vs star schema:
--   brand_tier        — Mass / Premium / Luxury (CMO strategic tier)
--   digital_priority  — TRUE if brand has digital-first strategy
--   sustainability_score — 1-10 ESG score (from L'Oreal for the Future report)
--   latam_launch_year — year brand launched in LATAM markets
--   parent_brand      — parent brand name (for brand family grouping)
-- ============================================================

CREATE OR REPLACE TABLE `loreal_latam_snowflake.dim_brand` AS
WITH base AS (
  SELECT DISTINCT
    brand,
    division
  FROM `loreal_latam.dim_product_clean`
  WHERE brand IS NOT NULL
),
enriched AS (
  SELECT
    ROW_NUMBER() OVER (ORDER BY brand ASC) AS brand_id,
    brand                                   AS brand_name,
    division,

    -- brand_tier: derived from division + brand name heuristics
    CASE
      WHEN UPPER(division) IN ('LUXE', 'LUXURY', 'PRESTIGE')        THEN 'Luxury'
      WHEN UPPER(division) IN ('PROFESSIONAL PRODUCTS', 'PPD')       THEN 'Premium'
      WHEN UPPER(division) IN ('CONSUMER PRODUCTS', 'CPD', 'ACTIVE COSMETICS') THEN 'Mass'
      ELSE 'Mass'
    END                                     AS brand_tier,

    -- is_luxury: boolean shortcut
    CASE
      WHEN UPPER(division) IN ('LUXE', 'LUXURY', 'PRESTIGE') THEN TRUE
      ELSE FALSE
    END                                     AS is_luxury,

    -- digital_priority: TRUE for brands with known digital-first strategy
    CASE
      WHEN UPPER(brand) IN ('MAYBELLINE', 'GARNIER', 'NYX', 'LANCOME') THEN TRUE
      ELSE FALSE
    END                                     AS digital_priority,

    -- sustainability_score: 1-10 ESG score proxy (illustrative)
    CASE
      WHEN UPPER(brand) IN ('GARNIER', 'BIOTHERM', 'KIEHL''S')          THEN 9
      WHEN UPPER(brand) IN ('LANCOME', 'YVES SAINT LAURENT')             THEN 8
      WHEN UPPER(brand) IN ('LOREAL PARIS', "L'OREAL PARIS")             THEN 8
      WHEN UPPER(brand) IN ('MAYBELLINE', 'KERASTASE')                   THEN 7
      WHEN UPPER(brand) IN ('REDKEN', 'MATRIX')                          THEN 7
      ELSE 6
    END                                     AS sustainability_score,

    -- latam_launch_year: approximate year brand arrived in LATAM
    CASE
      WHEN UPPER(brand) IN ('LANCOME', "L'OREAL PARIS", 'LOREAL PARIS') THEN 1990
      WHEN UPPER(brand) IN ('MAYBELLINE', 'GARNIER')                     THEN 1995
      WHEN UPPER(brand) IN ('KERASTASE', 'REDKEN', 'MATRIX')             THEN 2000
      WHEN UPPER(brand) IN ('NYX', 'IT COSMETICS')                       THEN 2015
      ELSE 2005
    END                                     AS latam_launch_year,

    'L''Oréal Group'                        AS parent_company

  FROM base
)
SELECT * FROM enriched
ORDER BY brand_id;

-- Validate dim_brand
SELECT
  brand_id,
  brand_name,
  division,
  brand_tier,
  is_luxury,
  digital_priority,
  sustainability_score,
  latam_launch_year
FROM `loreal_latam_snowflake.dim_brand`
ORDER BY brand_id;


-- ============================================================
-- STEP 9 — CREATE dim_category (normalised category layer)
--
-- New columns vs star schema:
--   growth_priority   — High / Medium / Low (from annual brand plan)
--   is_digital_first  — TRUE if category primarily sold online
--   margin_profile    — High / Medium / Low gross margin category
-- ============================================================

CREATE OR REPLACE TABLE `loreal_latam_snowflake.dim_category` AS
WITH base AS (
  SELECT DISTINCT
    category,
    subcategory
  FROM `loreal_latam.dim_product_clean`
  WHERE category IS NOT NULL
),
enriched AS (
  SELECT
    ROW_NUMBER() OVER (ORDER BY category ASC, subcategory ASC) AS category_id,
    category                                                      AS category_name,
    COALESCE(subcategory, category)                               AS subcategory_name,

    -- growth_priority: from strategic plan
    CASE
      WHEN LOWER(category) IN ('skincare', 'skin care', 'serum', 'moisturiser') THEN 'High'
      WHEN LOWER(category) IN ('makeup', 'colour', 'color cosmetics')           THEN 'High'
      WHEN LOWER(category) IN ('haircare', 'hair care', 'hair color')           THEN 'Medium'
      WHEN LOWER(category) IN ('fragrance', 'perfume')                          THEN 'Medium'
      ELSE 'Low'
    END                                                           AS growth_priority,

    -- is_digital_first: primarily purchased online
    CASE
      WHEN LOWER(category) IN ('skincare', 'skin care', 'serum') THEN TRUE
      ELSE FALSE
    END                                                           AS is_digital_first,

    -- margin_profile
    CASE
      WHEN LOWER(category) IN ('fragrance', 'perfume', 'skincare') THEN 'High'
      WHEN LOWER(category) IN ('makeup', 'colour cosmetics')        THEN 'High'
      WHEN LOWER(category) IN ('haircare', 'professional')          THEN 'Medium'
      ELSE 'Medium'
    END                                                           AS margin_profile

  FROM base
)
SELECT * FROM enriched
ORDER BY category_id;

-- Validate dim_category
SELECT
  category_id,
  category_name,
  subcategory_name,
  growth_priority,
  is_digital_first,
  margin_profile
FROM `loreal_latam_snowflake.dim_category`
ORDER BY category_id;


-- ============================================================
-- STEP 10 — CREATE dim_product_slim (normalised product layer)
--
-- This replaces dim_product_clean as the product dimension.
-- It holds ONLY the product-grain attributes.
-- Brand and category attributes live in dim_brand / dim_category.
-- ============================================================

CREATE OR REPLACE TABLE `loreal_latam_snowflake.dim_product_slim` AS
SELECT
  p.product_id,
  p.product_name,
  b.brand_id,
  c.category_id,
  -- keep denormalised copies for easy cross-validation only
  p.brand      AS brand_name_ref,
  p.category   AS category_name_ref
FROM `loreal_latam.dim_product_clean` p
LEFT JOIN `loreal_latam_snowflake.dim_brand`    b
       ON UPPER(TRIM(p.brand))    = UPPER(TRIM(b.brand_name))
LEFT JOIN `loreal_latam_snowflake.dim_category` c
       ON UPPER(TRIM(p.category)) = UPPER(TRIM(c.category_name))
      AND UPPER(TRIM(COALESCE(p.subcategory, p.category))) = UPPER(TRIM(c.subcategory_name));

-- Validate: row count should match dim_product_clean
SELECT COUNT(*) AS product_slim_rows FROM `loreal_latam_snowflake.dim_product_slim`;

-- Check for any products that failed to match a brand or category
SELECT
  product_id,
  product_name,
  brand_name_ref,
  category_name_ref,
  brand_id,
  category_id
FROM `loreal_latam_snowflake.dim_product_slim`
WHERE brand_id IS NULL OR category_id IS NULL;


-- ============================================================
-- STEP 11 — Final verification: full snowflake join
-- Check that fact → product_slim → brand → category all link up
-- ============================================================

SELECT
  f.transaction_date,
  g.country_name,
  b.brand_name,
  b.brand_tier,
  b.sustainability_score,
  cat.category_name,
  cat.growth_priority,
  ch.channel_name,
  ch.is_digital,
  seg.segment_name,
  f.revenue_usd,
  f.units_sold,
  f.margin_tier
FROM `loreal_latam_snowflake.fact_sales_clean`   f
JOIN `loreal_latam_snowflake.dim_product_slim`   ps  ON f.product_id    = ps.product_id
JOIN `loreal_latam_snowflake.dim_brand`           b   ON ps.brand_id     = b.brand_id
JOIN `loreal_latam_snowflake.dim_category`        cat ON ps.category_id  = cat.category_id
JOIN `loreal_latam_snowflake.dim_geography_clean` g   ON f.geography_id  = g.geography_id
JOIN `loreal_latam_snowflake.dim_channel_clean`   ch  ON f.channel_id    = ch.channel_id
JOIN `loreal_latam_snowflake.dim_segment_clean`   seg ON f.segment_id    = seg.segment_id
ORDER BY f.revenue_usd DESC
LIMIT 20;

-- Revenue by brand tier (NEW — only possible in snowflake schema)
SELECT
  b.brand_tier,
  b.division,
  COUNT(DISTINCT b.brand_id)  AS brand_count,
  ROUND(SUM(f.revenue_usd), 2) AS total_revenue,
  ROUND(AVG(b.sustainability_score), 1) AS avg_sustainability_score
FROM `loreal_latam_snowflake.fact_sales_clean`  f
JOIN `loreal_latam_snowflake.dim_product_slim`  ps ON f.product_id = ps.product_id
JOIN `loreal_latam_snowflake.dim_brand`          b ON ps.brand_id  = b.brand_id
GROUP BY b.brand_tier, b.division
ORDER BY total_revenue DESC;

-- Revenue by category growth priority (NEW — only possible in snowflake schema)
SELECT
  cat.growth_priority,
  cat.margin_profile,
  COUNT(DISTINCT cat.category_id) AS category_count,
  ROUND(SUM(f.revenue_usd), 2)    AS total_revenue
FROM `loreal_latam_snowflake.fact_sales_clean`   f
JOIN `loreal_latam_snowflake.dim_product_slim`   ps  ON f.product_id   = ps.product_id
JOIN `loreal_latam_snowflake.dim_category`        cat ON ps.category_id = cat.category_id
GROUP BY cat.growth_priority, cat.margin_profile
ORDER BY total_revenue DESC;
