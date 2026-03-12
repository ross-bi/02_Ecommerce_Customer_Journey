[![繁體中文](https://img.shields.io/badge/繁體中文-點擊查看-blue?style=for-the-badge)](README.zh-TW.md)
&nbsp;&nbsp;
[![简体中文](https://img.shields.io/badge/简体中文-点击查看-blue?style=for-the-badge)](README.zh-CN.md)

# E-Commerce Customer Journey Analytics

**BigQuery · PostgreSQL · dbt · Power BI**

---

## Project Overview

This project performs an end-to-end customer journey analysis using the [GA4 Obfuscated Sample E-Commerce dataset](https://console.cloud.google.com/bigquery?p=bigquery-public-data&d=ga4_obfuscated_sample_ecommerce) — a real-world obfuscated Google Analytics 4 dataset published by Google as a BigQuery public dataset.

The goal is to understand **how customers move through the purchase funnel**, identify high-value segments, and analyse conversion rates across traffic sources, devices, and geographies.

### What This Project Covers

- Extracting GA4 event data from **BigQuery** and loading into **PostgreSQL**
- Building a layered **dbt** transformation pipeline (staging → marts)
- Modelling a funnel fact table and customer dimension for Power BI analysis
- Analysing conversion rates, session behaviour, and customer lifetime value

---

## Dataset

| Item | Detail |
|---|---|
| Source | [BigQuery Public Data — GA4 Obfuscated Sample E-Commerce](https://console.cloud.google.com/bigquery?p=bigquery-public-data&d=ga4_obfuscated_sample_ecommerce) |
| Time Range | November 2020 (30 days) |
| Events Captured | `session_start`, `view_item`, `add_to_cart`, `begin_checkout`, `purchase` |
| Key Fields | event_date, event_time, event_name, user_pseudo_id, session_id, device_category, country, traffic_source, traffic_medium, purchase_revenue |

---

## Tools & Technologies

| Tool | Purpose |
|---|---|
| BigQuery | Source data extraction (GA4 public dataset) |
| PostgreSQL | Data warehouse — stores raw and transformed tables |
| dbt | Data transformation pipeline (staging + marts layers) |
| Power BI | Funnel visualisation and customer segmentation dashboard |
| GitHub | Version control and documentation |

---

## Architecture Overview

```
BigQuery (GA4 Public Data)
        │
        ▼  SQL extraction → CSV export
PostgreSQL: raw.ga4_events
        │
        ▼  dbt staging layer
stg_ga4_events          ← Cleaned, normalised events (incremental model)
        │
        ▼  dbt marts layer
fact_sessions           ← Session-level funnel flags + revenue (incremental)
dim_customers           ← Customer lifetime value + order count
dim_traffic             ← Traffic source/medium dimension
        │
        ▼
Power BI Dashboard
```

---

## 1. Data Extraction (BigQuery → PostgreSQL)

### BigQuery SQL — Funnel Event Extraction
```sql
SELECT
  event_date,
  TIMESTAMP_MICROS(event_timestamp)                                     AS event_time,
  event_name,
  user_pseudo_id,
  (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS session_id,
  device.category       AS device_category,
  device.operating_system,
  geo.country,
  geo.city,
  traffic_source.source AS traffic_source,
  traffic_source.medium AS traffic_medium,
  ecommerce.purchase_revenue,
  ecommerce.total_item_quantity
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20201130'
  AND event_name IN ('session_start','view_item','add_to_cart','begin_checkout','purchase')
```

The extracted data is loaded into `raw.ga4_events` in PostgreSQL for downstream dbt processing.

---

## 2. dbt Transformation Pipeline

### Staging Layer — `stg_ga4_events`

**Materialization**: Incremental (unique key: `session_id`)

Transformations applied:
- Null out `(not set)` values in device and geography fields
- Normalise noisy traffic sources (`(data deleted)`, `(direct)`, `<Other>` → `Unknown`)
- `COALESCE` purchase revenue and quantity nulls to 0
- Incremental filter: only processes records newer than the current max `event_time`

```sql
{{ config(materialized='incremental', unique_key='session_id') }}

SELECT
    event_date, event_time, event_name, user_pseudo_id, session_id,
    NULLIF(device_category, '(not set)')    AS device_category,
    NULLIF(country, '(not set)')            AS country,
    CASE WHEN traffic_source IN ('(data deleted)','(direct)','<Other>')
         THEN 'Unknown' ELSE traffic_source END AS traffic_source,
    COALESCE(purchase_revenue, 0)           AS purchase_revenue
FROM {{ source('raw', 'ga4_events') }}
{% if is_incremental() %}
  WHERE event_time > (SELECT max(event_time) FROM {{ this }})
{% endif %}
```

### Marts Layer

#### `fact_sessions` — Purchase Funnel Fact Table

**Materialization**: Incremental (unique key: `session_id`)

Each row represents one user session, with binary flags for each funnel stage:

| Column | Description |
|---|---|
| `session_id` | Unique session identifier |
| `customer_id` | User pseudo ID |
| `traffic_sk` | Surrogate key (traffic source + medium) |
| `device_category` | Device type for this session |
| `is_session_start` | 1 if session started |
| `is_view_item` | 1 if product was viewed |
| `is_add_to_cart` | 1 if item added to cart |
| `is_begin_checkout` | 1 if checkout initiated |
| `is_purchase` | 1 if purchase completed |
| `session_revenue` | Total purchase revenue in this session |

#### `dim_customers` — Customer Lifetime Value

| Column | Description |
|---|---|
| `customer_id` | User pseudo ID |
| `main_country` | Most common country |
| `lifetime_value` | Total purchase revenue across all sessions |
| `total_orders` | Total number of purchase events |

#### `dim_traffic` — Traffic Source Dimension

Surrogate key generated via `dbt_utils.generate_surrogate_key(['traffic_source', 'traffic_medium'])`, enabling clean joins from `fact_sessions`.

---

## 3. Key Analysis

### Funnel Conversion Rate
```sql
SELECT
    COUNT(DISTINCT CASE WHEN is_session_start = 1 THEN session_id END)  AS sessions,
    COUNT(DISTINCT CASE WHEN is_view_item     = 1 THEN session_id END)  AS viewed_item,
    COUNT(DISTINCT CASE WHEN is_add_to_cart   = 1 THEN session_id END)  AS added_to_cart,
    COUNT(DISTINCT CASE WHEN is_begin_checkout= 1 THEN session_id END)  AS began_checkout,
    COUNT(DISTINCT CASE WHEN is_purchase      = 1 THEN session_id END)  AS purchased
FROM marts.fact_sessions;
```

### High-Value Customer Segment
```sql
SELECT customer_id, main_country, lifetime_value, total_orders
FROM marts.dim_customers
WHERE total_orders >= 2
ORDER BY lifetime_value DESC
LIMIT 20;
```

### Conversion Rate by Traffic Source
```sql
SELECT
    t.traffic_source,
    COUNT(DISTINCT f.session_id)                                          AS total_sessions,
    SUM(f.is_purchase)                                                    AS purchases,
    ROUND(SUM(f.is_purchase)::NUMERIC / COUNT(DISTINCT f.session_id), 4) AS cvr
FROM marts.fact_sessions f
JOIN marts.dim_traffic t ON f.traffic_sk = t.traffic_sk
GROUP BY 1
ORDER BY cvr DESC;
```

---

## Project Structure

```
02_Ecommerce_Customer_Journey/
│
├── data/
│   └── raw_ga4_events.csv               # Extracted GA4 events (Nov 2020)
│
├── scripts/
│   ├── create_table.sql                 # PostgreSQL raw schema creation
│   └── copy_raw.sql                     # Load CSV into raw.ga4_events
│
├── ga4_dbt/                             # dbt project root
│   ├── dbt_project.yml
│   ├── packages.yml                     # dbt_utils dependency
│   ├── models/
│   │   ├── staging/
│   │   │   ├── _sources.yml             # Source definition (raw.ga4_events)
│   │   │   ├── schema.yml               # Column tests and descriptions
│   │   │   └── stg_ga4_events.sql       # Incremental staging model
│   │   └── marts/
│   │       ├── fact_sessions.sql        # Funnel fact table (incremental)
│   │       ├── dim_customers.sql        # Customer LTV dimension
│   │       └── dim_traffic.sql          # Traffic source dimension
│   ├── tests/                           # Custom dbt data tests
│   ├── macros/                          # dbt macros
│   └── analyses/                        # Ad-hoc analytical SQL
│
└── README.md
```

---

## How to Reproduce

**Prerequisites**: Google Cloud account (BigQuery access), PostgreSQL 14+, dbt-postgres, Power BI Desktop

1. **Extract from BigQuery**: Run the extraction SQL above in BigQuery and export as CSV
2. **Load to PostgreSQL**: Execute `scripts/create_table.sql` then `scripts/copy_raw.sql`
3. **Run dbt**: Navigate to `ga4_dbt/` and run:
   ```bash
   dbt deps       # Install dbt_utils
   dbt run        # Build all models
   dbt test       # Run data quality tests
   ```
4. **Open Power BI**: Connect to your PostgreSQL `marts` schema

---

## License

This project is licensed under the [MIT LICENSE](./LICENSE).
