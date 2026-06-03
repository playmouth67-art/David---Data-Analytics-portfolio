-- ═══════════════════════════════════════════════════════════════════════════
-- L'ORÉAL LATAM BI PLATFORM — BigQuery Data Quality & Cleaning Scripts
-- Project: gen-lang-client-0812859211 · Dataset: loreal_latam
-- Run each block independently in BigQuery Studio (Ctrl+Enter or Run button)
-- ═══════════════════════════════════════════════════════════════════════════


-- ───────────────────────────────────────────────────────────────────────────
-- SECTION 1 · AUDIT QUERIES
-- Run these first — they are all SELECT only, nothing changes
-- ───────────────────────────────────────────────────────────────────────────


-- ── 1.1  Row counts across all tables ─────────────────────────────────────
-- Expected: fact_sales=32000, dim_product=41, dim_geography=5,
--           dim_channel=7, dim_segment=6, dim_date=2557, security_mapping=7

SELECT 'fact_sales'       AS table_name, COUNT(*) AS row_count FROM `loreal_latam.fact_sales`
UNION ALL
SELECT 'dim_product',      COUNT(*) FROM `loreal_latam.dim_product`
UNION ALL
SELECT 'dim_geography',    COUNT(*) FROM `loreal_latam.dim_geography`
UNION ALL
SELECT 'dim_channel',      COUNT(*) FROM `loreal_latam.dim_channel`
UNION ALL
SELECT 'dim_segment',      COUNT(*) FROM `loreal_latam.dim_segment`
UNION ALL
SELECT 'dim_date',         COUNT(*) FROM `loreal_latam.dim_date`
UNION ALL
SELECT 'security_mapping', COUNT(*) FROM `loreal_latam.security_mapping`
ORDER BY row_count DESC;


-- ── 1.2  Duplicate transactions in fact_sales ─────────────────────────────
-- Duplicates on transactionid = data pipeline double-load; should be 0

SELECT
    transactionid,
    COUNT(*) AS occurrences
FROM `loreal_latam.fact_sales`
GROUP BY transactionid
HAVING COUNT(*) > 1
ORDER BY occurrences DESC
LIMIT 20;


-- ── 1.3  Duplicate keys in dimension tables ───────────────────────────────
-- Any result here = broken star schema

SELECT 'dim_product duplicate productkey' AS check_name, COUNT(*) - COUNT(DISTINCT productkey) AS duplicates FROM `loreal_latam.dim_product`
UNION ALL
SELECT 'dim_geography duplicate geokey',   COUNT(*) - COUNT(DISTINCT geokey)    FROM `loreal_latam.dim_geography`
UNION ALL
SELECT 'dim_channel duplicate channelkey', COUNT(*) - COUNT(DISTINCT channelkey) FROM `loreal_latam.dim_channel`
UNION ALL
SELECT 'dim_segment duplicate segmentkey', COUNT(*) - COUNT(DISTINCT segmentkey) FROM `loreal_latam.dim_segment`
UNION ALL
SELECT 'dim_date duplicate date',          COUNT(*) - COUNT(DISTINCT date)       FROM `loreal_latam.dim_date`;


-- ── 1.4  NULL analysis — fact_sales ──────────────────────────────────────
-- Count nulls in every column of the fact table

SELECT
    COUNTIF(transactionid  IS NULL) AS null_transactionid,
    COUNTIF(date           IS NULL) AS null_date,
    COUNTIF(productkey     IS NULL) AS null_productkey,
    COUNTIF(geokey         IS NULL) AS null_geokey,
    COUNTIF(channelkey     IS NULL) AS null_channelkey,
    COUNTIF(segmentkey     IS NULL) AS null_segmentkey,
    COUNTIF(quantity       IS NULL) AS null_quantity,
    COUNTIF(unitprice_usd  IS NULL) AS null_unitprice,
    COUNTIF(revenue_usd    IS NULL) AS null_revenue_usd,
    COUNTIF(revenue_local  IS NULL) AS null_revenue_local,
    COUNTIF(currency       IS NULL) AS null_currency,
    COUNTIF(cogs_usd       IS NULL) AS null_cogs_usd,
    COUNTIF(margin_usd     IS NULL) AS null_margin_usd,
    COUNTIF(margin_pct     IS NULL) AS null_margin_pct
FROM `loreal_latam.fact_sales`;


-- ── 1.5  NULL analysis — dimension tables ────────────────────────────────

SELECT
    COUNTIF(productkey  IS NULL) AS null_productkey,
    COUNTIF(brand       IS NULL) AS null_brand,
    COUNTIF(division    IS NULL) AS null_division,
    COUNTIF(category    IS NULL) AS null_category,
    COUNTIF(subcategory IS NULL) AS null_subcategory
FROM `loreal_latam.dim_product`;

SELECT
    COUNTIF(geokey      IS NULL) AS null_geokey,
    COUNTIF(country     IS NULL) AS null_country,
    COUNTIF(countrycode IS NULL) AS null_countrycode,
    COUNTIF(currency    IS NULL) AS null_currency
FROM `loreal_latam.dim_geography`;


-- ── 1.6  Referential integrity — orphan rows in fact_sales ───────────────
-- Orphan = a key in fact_sales that does NOT exist in the dimension
-- Any result = broken relationship in Power BI

SELECT 'orphan productkey' AS issue, COUNT(*) AS orphan_rows
FROM `loreal_latam.fact_sales` f
WHERE NOT EXISTS (
    SELECT 1 FROM `loreal_latam.dim_product` p WHERE p.productkey = f.productkey
)
UNION ALL
SELECT 'orphan geokey', COUNT(*)
FROM `loreal_latam.fact_sales` f
WHERE NOT EXISTS (
    SELECT 1 FROM `loreal_latam.dim_geography` g WHERE g.geokey = f.geokey
)
UNION ALL
SELECT 'orphan channelkey', COUNT(*)
FROM `loreal_latam.fact_sales` f
WHERE NOT EXISTS (
    SELECT 1 FROM `loreal_latam.dim_channel` c WHERE c.channelkey = f.channelkey
)
UNION ALL
SELECT 'orphan segmentkey', COUNT(*)
FROM `loreal_latam.fact_sales` f
WHERE NOT EXISTS (
    SELECT 1 FROM `loreal_latam.dim_segment` s WHERE s.segmentkey = f.segmentkey
)
UNION ALL
SELECT 'orphan date', COUNT(*)
FROM `loreal_latam.fact_sales` f
WHERE NOT EXISTS (
    SELECT 1 FROM `loreal_latam.dim_date` d WHERE d.date = f.date
);


-- ── 1.7  Value range validation — revenue, quantity, margin ──────────────
-- Flags: negative revenue, negative quantity, impossible margins (>100% or <0%)

SELECT
    COUNTIF(revenue_usd  < 0)    AS negative_revenue,
    COUNTIF(quantity     <= 0)   AS zero_or_neg_quantity,
    COUNTIF(margin_pct   < 0)    AS negative_margin,
    COUNTIF(margin_pct   > 100)  AS margin_over_100pct,
    COUNTIF(discount_pct < 0)    AS negative_discount,
    COUNTIF(discount_pct > 100)  AS discount_over_100pct,
    COUNTIF(cogs_usd     < 0)    AS negative_cogs,
    COUNTIF(unitprice_usd <= 0)  AS zero_or_neg_price
FROM `loreal_latam.fact_sales`;


-- ── 1.8  Date range validation ────────────────────────────────────────────
-- Should be Jan 2022 – Dec 2024

SELECT
    MIN(date)   AS earliest_date,
    MAX(date)   AS latest_date,
    COUNT(DISTINCT date) AS distinct_dates,
    COUNT(DISTINCT EXTRACT(YEAR FROM date)) AS distinct_years
FROM `loreal_latam.fact_sales`;


-- ── 1.9  Revenue distribution by country — sanity check ──────────────────
-- Expected weight: MX 30%, BR 25%, CO 20%, AR 15%, CL 10% (approx)

SELECT
    g.countrycode,
    g.country,
    COUNT(*)                                                  AS transactions,
    ROUND(SUM(f.revenue_usd), 0)                             AS total_revenue_usd,
    ROUND(SUM(f.revenue_usd) / SUM(SUM(f.revenue_usd))
          OVER () * 100, 1)                                  AS revenue_share_pct
FROM `loreal_latam.fact_sales`   f
JOIN `loreal_latam.dim_geography` g ON g.geokey = f.geokey
GROUP BY g.countrycode, g.country
ORDER BY total_revenue_usd DESC;


-- ── 1.10  Revenue & margin stats — outlier detection ─────────────────────

SELECT
    ROUND(AVG(revenue_usd), 2)                    AS avg_revenue_per_txn,
    ROUND(STDDEV(revenue_usd), 2)                 AS stddev_revenue,
    ROUND(APPROX_QUANTILES(revenue_usd, 100)[OFFSET(1)],   2) AS p1_revenue,
    ROUND(APPROX_QUANTILES(revenue_usd, 100)[OFFSET(25)],  2) AS p25_revenue,
    ROUND(APPROX_QUANTILES(revenue_usd, 100)[OFFSET(50)],  2) AS median_revenue,
    ROUND(APPROX_QUANTILES(revenue_usd, 100)[OFFSET(75)],  2) AS p75_revenue,
    ROUND(APPROX_QUANTILES(revenue_usd, 100)[OFFSET(99)],  2) AS p99_revenue,
    ROUND(MAX(revenue_usd), 2)                    AS max_revenue,
    ROUND(AVG(margin_pct), 1)                     AS avg_margin_pct
FROM `loreal_latam.fact_sales`;


-- ── 1.11  Currency consistency — fact vs. geography ───────────────────────
-- Each country should use only its assigned currency

SELECT
    g.countrycode,
    f.currency,
    COUNT(*) AS row_count
FROM `loreal_latam.fact_sales`    f
JOIN `loreal_latam.dim_geography`  g ON g.geokey = f.geokey
GROUP BY g.countrycode, f.currency
ORDER BY g.countrycode, row_count DESC;


-- ── 1.12  Year-Month transaction density — no gaps? ───────────────────────

SELECT
    EXTRACT(YEAR  FROM date) AS sale_year,
    EXTRACT(MONTH FROM date) AS sale_month,
    COUNT(*)                 AS transactions,
    ROUND(SUM(revenue_usd),0) AS revenue_usd
FROM `loreal_latam.fact_sales`
GROUP BY sale_year, sale_month
ORDER BY sale_year, sale_month;


-- ───────────────────────────────────────────────────────────────────────────
-- SECTION 2 · CLEANING QUERIES
-- These CREATE clean / corrected tables. Safe to run — creates new tables,
-- does NOT overwrite your originals.
-- ───────────────────────────────────────────────────────────────────────────


-- ── 2.1  Create a deduplicated fact table ─────────────────────────────────
-- Keeps the first occurrence of each transactionid, drops true duplicates.
-- Use fact_sales_clean as your Power BI source instead of fact_sales.

CREATE OR REPLACE TABLE `loreal_latam.fact_sales_clean` AS
SELECT * EXCEPT (row_num)
FROM (
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY transactionid ORDER BY date) AS row_num
    FROM `loreal_latam.fact_sales`
)
WHERE row_num = 1;

-- Verify dedup count:
SELECT
    (SELECT COUNT(*) FROM `loreal_latam.fact_sales`)       AS original_rows,
    (SELECT COUNT(*) FROM `loreal_latam.fact_sales_clean`) AS clean_rows,
    (SELECT COUNT(*) FROM `loreal_latam.fact_sales`)
    - (SELECT COUNT(*) FROM `loreal_latam.fact_sales_clean`) AS duplicates_removed;


-- ── 2.2  Add a derived margin_tier column ────────────────────────────────
-- Categorizes each transaction by margin band — useful for Power BI slicers
-- and conditional formatting without creating a calculated column in PBI.

CREATE OR REPLACE TABLE `loreal_latam.fact_sales_clean` AS
SELECT
    *,
    CASE
        WHEN margin_pct >= 70 THEN 'Premium (70%+)'
        WHEN margin_pct >= 55 THEN 'Healthy (55–70%)'
        WHEN margin_pct >= 40 THEN 'Standard (40–55%)'
        ELSE                       'Low (<40%)'
    END AS margin_tier,

    -- Revenue bucket for histogram / distribution visuals
    CASE
        WHEN revenue_usd >= 500  THEN '500+'
        WHEN revenue_usd >= 200  THEN '200–499'
        WHEN revenue_usd >= 100  THEN '100–199'
        WHEN revenue_usd >= 50   THEN '50–99'
        ELSE                          '<50'
    END AS revenue_bucket

FROM (
    SELECT * EXCEPT (row_num)
    FROM (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY transactionid ORDER BY date) AS row_num
        FROM `loreal_latam.fact_sales`
    )
    WHERE row_num = 1
);


-- ── 2.3  Standardize text casing in dimension tables ─────────────────────
-- Ensures consistent UPPER/Title Case — prevents double-counting in PBI
-- when "mexico" ≠ "Mexico" ≠ "MEXICO"

CREATE OR REPLACE TABLE `loreal_latam.dim_geography_clean` AS
SELECT
    geokey,
    INITCAP(country)            AS country,
    UPPER(countrycode)          AS countrycode,
    INITCAP(region)             AS region,
    UPPER(currency)             AS currency,
    fx_rate_to_usd
FROM `loreal_latam.dim_geography`;

CREATE OR REPLACE TABLE `loreal_latam.dim_product_clean` AS
SELECT
    productkey,
    INITCAP(brand)              AS brand,
    INITCAP(division)           AS division,
    INITCAP(category)           AS category,
    INITCAP(subcategory)        AS subcategory,
    unitprice_usd,
    cogs_pct
FROM `loreal_latam.dim_product`;

CREATE OR REPLACE TABLE `loreal_latam.dim_channel_clean` AS
SELECT
    channelkey,
    INITCAP(channel)            AS channel,
    INITCAP(channeltype)        AS channeltype,
    revenue_weight,
    -- Derived: is this a digital channel?
    CASE WHEN LOWER(channel) IN ('e-commerce', 'd2c') THEN TRUE ELSE FALSE END AS is_digital
FROM `loreal_latam.dim_channel`;

CREATE OR REPLACE TABLE `loreal_latam.dim_segment_clean` AS
SELECT
    segmentkey,
    INITCAP(segment)            AS segment,
    INITCAP(description)        AS description,
    INITCAP(spendlevel)         AS spendlevel
FROM `loreal_latam.dim_segment`;

CREATE OR REPLACE TABLE `loreal_latam.security_mapping_clean` AS
SELECT
    LOWER(TRIM(useremail))      AS useremail,
    UPPER(TRIM(countrycode))    AS countrycode,
    UPPER(TRIM(accesslevel))    AS accesslevel
FROM `loreal_latam.security_mapping`;


-- ── 2.4  Create a full enriched fact view (Gold layer) ───────────────────
-- Joins fact + all clean dimensions into one flat view.
-- Power BI can use this as a single DirectQuery source for exploration.
-- For Import mode, use the individual clean tables (star schema).

CREATE OR REPLACE VIEW `loreal_latam.v_sales_enriched` AS
SELECT
    f.transactionid,
    f.date,
    f.year,
    f.month,
    f.quarter,
    f.quantity,
    f.unitprice_usd,
    f.discount_pct,
    f.revenue_usd,
    f.revenue_local,
    f.currency,
    f.cogs_usd,
    f.margin_usd,
    f.margin_pct,
    f.margin_tier,
    f.revenue_bucket,

    -- Product
    p.brand,
    p.division,
    p.category,
    p.subcategory,

    -- Geography
    g.country,
    g.countrycode,
    g.region,

    -- Channel
    c.channel,
    c.channeltype,
    c.is_digital,

    -- Segment
    s.segment,
    s.spendlevel,

    -- Date enrichment
    d.month_name,
    d.quarter_year,
    d.weekday_name,
    d.is_weekend,
    d.is_holiday_season

FROM `loreal_latam.fact_sales_clean`    f
JOIN `loreal_latam.dim_product_clean`   p ON p.productkey  = f.productkey
JOIN `loreal_latam.dim_geography_clean` g ON g.geokey      = f.geokey
JOIN `loreal_latam.dim_channel_clean`   c ON c.channelkey  = f.channelkey
JOIN `loreal_latam.dim_segment_clean`   s ON s.segmentkey  = f.segmentkey
JOIN `loreal_latam.dim_date`            d ON d.date        = f.date;


-- ───────────────────────────────────────────────────────────────────────────
-- SECTION 3 · POST-CLEAN VALIDATION
-- Run after Section 2 to confirm clean tables are correct
-- ───────────────────────────────────────────────────────────────────────────


-- ── 3.1  Final row counts — clean tables ──────────────────────────────────

SELECT 'fact_sales_clean'        AS table_name, COUNT(*) AS rows FROM `loreal_latam.fact_sales_clean`
UNION ALL
SELECT 'dim_product_clean',      COUNT(*) FROM `loreal_latam.dim_product_clean`
UNION ALL
SELECT 'dim_geography_clean',    COUNT(*) FROM `loreal_latam.dim_geography_clean`
UNION ALL
SELECT 'dim_channel_clean',      COUNT(*) FROM `loreal_latam.dim_channel_clean`
UNION ALL
SELECT 'dim_segment_clean',      COUNT(*) FROM `loreal_latam.dim_segment_clean`
ORDER BY rows DESC;


-- ── 3.2  Preview enriched Gold view ───────────────────────────────────────

SELECT *
FROM `loreal_latam.v_sales_enriched`
LIMIT 10;


-- ── 3.3  Revenue summary by country & division — quick sanity check ───────

SELECT
    countrycode,
    division,
    COUNT(*)                         AS transactions,
    ROUND(SUM(revenue_usd), 0)       AS total_revenue_usd,
    ROUND(AVG(margin_pct), 1)        AS avg_margin_pct
FROM `loreal_latam.v_sales_enriched`
GROUP BY countrycode, division
ORDER BY countrycode, total_revenue_usd DESC;


-- ── 3.4  Margin tier distribution ─────────────────────────────────────────

SELECT
    margin_tier,
    COUNT(*)                                              AS transactions,
    ROUND(COUNT(*) / SUM(COUNT(*)) OVER () * 100, 1)    AS pct_of_total
FROM `loreal_latam.fact_sales_clean`
GROUP BY margin_tier
ORDER BY transactions DESC;


-- ── 3.5  Digital vs. physical channel split ───────────────────────────────

SELECT
    c.is_digital,
    c.channeltype,
    COUNT(*)                     AS transactions,
    ROUND(SUM(f.revenue_usd), 0) AS revenue_usd
FROM `loreal_latam.fact_sales_clean`  f
JOIN `loreal_latam.dim_channel_clean` c ON c.channelkey = f.channelkey
GROUP BY c.is_digital, c.channeltype
ORDER BY revenue_usd DESC;


-- ═══════════════════════════════════════════════════════════════════════════
-- SUMMARY: What to use in Power BI
-- ───────────────────────────────────────────────────────────────────────────
-- Star schema (recommended — Import mode, best performance):
--   fact_sales_clean       ← main fact table
--   dim_product_clean      ← product dimension
--   dim_geography_clean    ← geography dimension
--   dim_channel_clean      ← channel dimension (includes is_digital flag)
--   dim_segment_clean      ← segment dimension
--   dim_date               ← date dimension (no changes needed)
--   security_mapping_clean ← for dynamic RLS
--
-- Gold view (optional — DirectQuery for ad-hoc / analyst sandbox):
--   v_sales_enriched       ← fully joined flat view, all columns available
-- ═══════════════════════════════════════════════════════════════════════════
