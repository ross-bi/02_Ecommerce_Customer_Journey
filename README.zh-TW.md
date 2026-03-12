[![English](https://img.shields.io/badge/English-Click_Here-blue?style=for-the-badge)](README.md)

# 電商顧客旅程分析

**BigQuery · PostgreSQL · dbt · Power BI**

---

## 專案概述

本專案使用 [GA4 Obfuscated Sample E-Commerce 資料集](https://console.cloud.google.com/bigquery?p=bigquery-public-data&d=ga4_obfuscated_sample_ecommerce)（Google 發布的 BigQuery 公開資料集，真實電商資料經過混淆處理），進行端對端的電商顧客旅程分析。

目標是了解**顧客如何在購物漏斗中移動**、識別高價值客群，以及分析各流量來源、裝置與地區的轉換率表現。

### 涵蓋範疇

- 從 **BigQuery** 提取 GA4 事件資料並載入 **PostgreSQL**
- 建立分層 **dbt** 資料轉換流程（staging → marts）
- 建模購物漏斗事實表與顧客維度表，供 Power BI 分析使用
- 分析轉換率、工作階段行為及顧客終身價值

---

## 資料集

| 項目 | 說明 |
|---|---|
| 來源 | [BigQuery 公開資料 — GA4 Obfuscated Sample E-Commerce](https://console.cloud.google.com/bigquery?p=bigquery-public-data&d=ga4_obfuscated_sample_ecommerce) |
| 時間範圍 | 2020 年 11 月（共 30 天）|
| 擷取事件 | `session_start`、`view_item`、`add_to_cart`、`begin_checkout`、`purchase` |
| 主要欄位 | 事件日期、事件時間、事件名稱、用戶 ID、工作階段 ID、裝置類別、國家/地區、流量來源、購買金額 |

---

## 工具與技術

| 工具 | 用途 |
|---|---|
| BigQuery | 來源資料提取（GA4 公開資料集）|
| PostgreSQL | 資料倉儲 — 儲存原始及轉換後的資料表 |
| dbt | 資料轉換流程（staging + marts 分層）|
| Power BI | 漏斗視覺化與顧客分群儀表板 |
| GitHub | 版本控制與文件記錄 |

---

## 架構概覽

```
BigQuery（GA4 公開資料）
        │
        ▼  SQL 提取 → CSV 匯出
PostgreSQL: raw.ga4_events
        │
        ▼  dbt staging 層
stg_ga4_events          ← 清理、正規化的事件資料（遞增模型）
        │
        ▼  dbt marts 層
fact_sessions           ← 工作階段層級漏斗標記 + 收入（遞增模型）
dim_customers           ← 顧客終身價值 + 訂單數量
dim_traffic             ← 流量來源/媒介維度表
        │
        ▼
Power BI 儀表板
```

---

## 一、資料提取（BigQuery → PostgreSQL）

### BigQuery SQL — 漏斗事件提取
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

提取的資料載入 PostgreSQL 的 `raw.ga4_events`，供 dbt 後續處理。

---

## 二、dbt 資料轉換流程

### Staging 層 — `stg_ga4_events`

**物化方式**：遞增模型（unique_key：`session_id`）

套用的轉換：
- 將裝置及地區欄位的 `(not set)` 值設為 NULL
- 正規化雜訊流量來源（`(data deleted)`、`(direct)`、`<Other>` → `Unknown`）
- 購買金額及數量的 NULL 補 0（COALESCE）
- 遞增篩選：僅處理比現有資料庫中最新 `event_time` 更新的記錄

### Marts 層

#### `fact_sessions` — 購物漏斗事實表

**物化方式**：遞增模型（unique_key：`session_id`）

每一列代表一個用戶工作階段，包含各漏斗階段的二元標記：

| 欄位 | 說明 |
|---|---|
| `session_id` | 唯一工作階段識別碼 |
| `customer_id` | 用戶 pseudo ID |
| `traffic_sk` | 代理鍵（流量來源 + 媒介）|
| `device_category` | 此工作階段的裝置類型 |
| `is_session_start` | 1 = 工作階段已開始 |
| `is_view_item` | 1 = 已瀏覽商品 |
| `is_add_to_cart` | 1 = 已加入購物車 |
| `is_begin_checkout` | 1 = 已開始結帳 |
| `is_purchase` | 1 = 已完成購買 |
| `session_revenue` | 此工作階段的購買總金額 |

#### `dim_customers` — 顧客終身價值維度

| 欄位 | 說明 |
|---|---|
| `customer_id` | 用戶 pseudo ID |
| `main_country` | 最常出現的國家/地區 |
| `lifetime_value` | 所有工作階段的購買總金額 |
| `total_orders` | 購買事件總次數 |

#### `dim_traffic` — 流量來源維度

透過 `dbt_utils.generate_surrogate_key(['traffic_source', 'traffic_medium'])` 生成代理鍵，便於從 `fact_sessions` 進行乾淨的 JOIN 關聯。

---

## 三、主要分析

### 漏斗轉換率
```sql
SELECT
    COUNT(DISTINCT CASE WHEN is_session_start = 1 THEN session_id END) AS sessions,
    COUNT(DISTINCT CASE WHEN is_view_item     = 1 THEN session_id END) AS viewed_item,
    COUNT(DISTINCT CASE WHEN is_add_to_cart   = 1 THEN session_id END) AS added_to_cart,
    COUNT(DISTINCT CASE WHEN is_begin_checkout= 1 THEN session_id END) AS began_checkout,
    COUNT(DISTINCT CASE WHEN is_purchase      = 1 THEN session_id END) AS purchased
FROM marts.fact_sessions;
```

### 高價值顧客分群
```sql
SELECT customer_id, main_country, lifetime_value, total_orders
FROM marts.dim_customers
WHERE total_orders >= 2
ORDER BY lifetime_value DESC
LIMIT 20;
```

### 各流量來源轉換率
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

## 專案結構

```
02_Ecommerce_Customer_Journey/
│
├── data/
│   └── raw_ga4_events.csv               # 提取的 GA4 事件（2020 年 11 月）
│
├── scripts/
│   ├── create_table.sql                 # PostgreSQL raw 綱要建立
│   └── copy_raw.sql                     # 載入 CSV 至 raw.ga4_events
│
├── ga4_dbt/                             # dbt 專案根目錄
│   ├── dbt_project.yml
│   ├── packages.yml                     # dbt_utils 套件依賴
│   ├── models/
│   │   ├── staging/
│   │   │   ├── _sources.yml             # 來源定義（raw.ga4_events）
│   │   │   ├── schema.yml               # 欄位測試與說明
│   │   │   └── stg_ga4_events.sql       # 遞增 staging 模型
│   │   └── marts/
│   │       ├── fact_sessions.sql        # 漏斗事實表（遞增）
│   │       ├── dim_customers.sql        # 顧客 LTV 維度
│   │       └── dim_traffic.sql          # 流量來源維度
│   ├── tests/                           # 自訂 dbt 資料測試
│   ├── macros/                          # dbt 巨集
│   └── analyses/                        # 臨時分析 SQL
│
└── README.md
```

---

## 如何重現本專案

**前置需求**：Google Cloud 帳戶（BigQuery 存取）、PostgreSQL 14+、dbt-postgres、Power BI Desktop

1. **從 BigQuery 提取**：在 BigQuery 執行上述提取 SQL 並匯出為 CSV
2. **載入 PostgreSQL**：執行 `scripts/create_table.sql`，再執行 `scripts/copy_raw.sql`
3. **執行 dbt**：進入 `ga4_dbt/` 目錄並執行：
   ```bash
   dbt deps       # 安裝 dbt_utils
   dbt run        # 建立所有模型
   dbt test       # 執行資料品質測試
   ```
4. **開啟 Power BI**：連接至 PostgreSQL 的 `marts` 綱要

---

## 授權條款

本專案採用 MIT License 授權。
