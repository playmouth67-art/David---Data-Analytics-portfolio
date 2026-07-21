# Investment Analytics Manager — Interview Assessment (Task 1)

**Prepared by David Adrián González Molina**

A one-page executive dashboard concept for senior marketers, built from the supplied
MKT Digital Data. The goal: give CMOs and above a top-level read on digital channel
performance, and make the odd patterns easy to spot and worth a second look.

---

## The case in one line

Across two years, media spend grew **+19.7%** ($146.5M → $175.5M) while impressions
stayed essentially flat (**+0.4%**) and CPM rose **+19.3%**. More budget bought
more-expensive impressions, not a bigger audience. The biggest-spending channels (Meta,
TikTok) are not the most efficient; YouTube and Google Ads return far more value per
dollar yet receive only ~28% of spend.

## Key assumptions

- **Vertical:** Consumer Health / OTC.
- **Market demand & competitive share** are modelled from category benchmarks and
  flagged as assumptions in the deck (the supplied dataset covers owned channel
  performance only).
- **Period:** FY2023–FY2024. Data is synthetic / for demonstration.
- **Efficiency Index** = Weighted Score ÷ Spend, where
  Weighted Score = Clicks×1 + Video Views×0.1 + Engagements×0.5.

---

## What's in this package

### 1_Presentations
- **Jellyfish_Task1_Dashboard_Assessment.pptx** — the assessment answer: assumptions,
  a one-page dashboard wireframe, and the build plan (technologies, tasks &
  responsibilities, risks).
- **Jellyfish_Data_Storytelling.pptx** — a narrative walk-through of the core insight
  (spend up, reach flat) and the recommended reallocation, with the solution design.

### 2_Dashboard
- **Jellyfish_Media_Efficiency_Dashboard.pdf** — exported view of the built dashboard.

### 3_Source_Data
- **Jellyfish_Marketing_Data_Source.xlsx** — the original supplied marketing dataset.
- **Jellyfish_mkt_digital_raw.csv** — the raw extract as a flat CSV.
- **Jellyfish_dashboard_ready.csv** — analysis-ready table with derived metrics
  (Weighted Score, CPM).
- **Jellyfish_LookerSource_GoogleSheets.csv** — the same table prepared as a durable
  Looker Studio source (English column names).

### 4_SQL
- **jellyfish_view_dashboard_ready.sql** — the BigQuery view that powers the dashboard:
  one curated source of truth using COALESCE on additive metrics, SAFE_DIVIDE on
  ratios, a weighted CPM (Σspend ÷ Σimpr × 1000) and a single Efficiency Index.

---

## How it was built

**Data preparation:** Google BigQuery (one curated view as the single source of truth).
**Visualization:** Looker Studio (KPI scorecards, spend-vs-reach trend, channel mix on
one page, with period and channel filters), tuned for a five-second executive read.
