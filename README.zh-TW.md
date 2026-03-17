[![English](https://img.shields.io/badge/English-Click_Here-blue?style=for-the-badge)](README.md)
&nbsp;&nbsp;
[![简体中文](https://img.shields.io/badge/简体中文-点击查看-blue?style=for-the-badge)](README.zh-CN.md)

# 電商顧客旅程分析

**BigQuery · PostgreSQL · dbt · Power BI**

> 端對端分析流程：從 GA4 原始事件資料到互動式 Power BI 儀表板 — 涵蓋資料提取、轉換、測試與視覺化。

---

## 專案概述

本專案使用 [GA4 Obfuscated Sample E-Commerce 資料集](https://console.cloud.google.com/bigquery?p=bigquery-public-data&d=ga4_obfuscated_sample_ecommerce)（Google 發布的 BigQuery 公開資料集，真實電商資料經過混淆處理），進行完整的電商顧客旅程分析。

目標是了解**顧客如何在購物漏斗中移動**、識別高價值客群，以及分析各流量來源、裝置與地區的轉換率表現。

### 涵蓋範疇

- 從 **BigQuery** 提取 GA4 事件資料並載入 **PostgreSQL**
- 建立分層 **dbt** 轉換流程（staging → marts），包含 **26 項資料品質測試**
- 建模星狀綱要：漏斗事實表 + 顧客維度表 + 流量維度表
- 建立 **3 頁 Power BI 互動式儀表板**：漏斗分析、流量表現、顧客分群
- 在問題解決筆記本中記錄資料異常與設計決策

---

## 儀表板預覽

| 第 1 頁 — 總覽 | 第 2 頁 — 轉換與流量 | 第 3 頁 — 顧客分群 |
|:---:|:---:|:---:|
| ![總覽](screenshot/bi01.png) | ![轉換與流量](screenshot/bi02.png) | ![顧客分群](screenshot/bi03.png) |

**第 1 頁** — KPI 卡片、購物漏斗圖、裝置分佈、各國收入  
**第 2 頁** — 各流量媒介/來源的轉換率、裝置層級指標、流量 × 裝置交叉分析  
**第 3 頁** — 顧客終身價值分佈、LTV vs 訂單數散佈圖、高價值顧客排行

---

## 資料集

| 項目 | 說明 |
|---|---|
| 來源 | [BigQuery 公開資料 — GA4 Obfuscated Sample E-Commerce](https://console.cloud.google.com/bigquery?p=bigquery-public-data&d=ga4_obfuscated_sample_ecommerce) |
| 時間範圍 | 2020 年 11 月（共 30 天）|
| 資料規模 | 約 274,000 筆事件 · 約 104,000 個工作階段 · 約 79,000 位用戶 · 約 $144K 營收 |
| 擷取事件 | `session_start`、`view_item`、`add_to_cart`、`begin_checkout`、`purchase` |
| 主要欄位 | event_date、event_time、event_name、user_pseudo_id、session_id、device_category、operating_system、country、city、traffic_source、traffic_medium、purchase_revenue、total_item_quantity |

---

## 工具與技術

| 工具 | 用途 |
|---|---|
| BigQuery | 來源資料提取（GA4 公開資料集）|
| PostgreSQL | 資料倉儲 — 儲存原始及轉換後的資料表 |
| dbt | 資料轉換流程（staging + marts 分層）含 schema 測試 |
| Power BI | 3 頁互動式儀表板（漏斗、流量、顧客分群）|
| GitHub | 版本控制與文件記錄 |

---

## 架構

```
BigQuery (GA4 Public Data)
        |
        v  SQL export --> CSV
PostgreSQL: raw.ga4_events
        |
        v  dbt staging layer
stg_ga4_events              <-- Cleaned & normalised (incremental)
        |                       . (not set)      --> NULL
        |                       . (data deleted)  --> Unknown
        |                       . <Other>         --> Unknown
        |                       . (direct)        --> Direct
        |                       . NULL revenue    --> 0
        |
        v  dbt marts layer (star schema)
+-------------------+    +-------------------+    +-------------------+
|  fact_sessions    |    |  dim_customers    |    |  dim_traffic      |
|  (incremental)    |<-->|  (table)          |    |  (table)          |
|  Session funnel   |    |  LTV + orders     |    |  Source / medium  |
|  flags + revenue  |    |  per customer     |    |  surrogate key    |
+-------------------+    +-------------------+    +-------------------+
        |
        v  26 schema tests (unique, not_null, accepted_values, relationships)
        |
        v
   Power BI Dashboard (3 pages)
```

---

## 一、資料提取（BigQuery → PostgreSQL）

### BigQuery SQL — 漏斗事件提取

```sql
SELECT
  event_date,
  TIMESTAMP_MICROS(event_timestamp)       AS event_time,
  event_name,
  user_pseudo_id,
  (SELECT value.int_value
   FROM UNNEST(event_params)
   WHERE key = 'ga_session_id')           AS session_id,
  device.category                         AS device_category,
  device.operating_system,
  geo.country,
  geo.city,
  traffic_source.source                   AS traffic_source,
  traffic_source.medium                   AS traffic_medium,
  ecommerce.purchase_revenue,
  ecommerce.total_item_quantity
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20201130'
  AND event_name IN (
    'session_start','view_item','add_to_cart','begin_checkout','purchase'
  )
```

提取的 CSV 透過 `scripts/` 內的腳本載入 PostgreSQL 的 `raw.ga4_events`。

---

## 二、dbt 資料轉換流程

### Staging 層 — `stg_ga4_events`

**物化方式**：遞增模型（unique_key：`session_id`）

| 轉換項目 | 邏輯 |
|---|---|
| 清理裝置與地區欄位 | `NULLIF(device_category, '(not set)')` — 移除佔位值 |
| 正規化流量來源 | `(data deleted)` / `<Other>` → `Unknown`；`(direct)` → `Direct` |
| 正規化流量媒介 | `(data deleted)` / `(none)` / `<Other>` → `Unknown` |
| 填補缺失金額 | `COALESCE(purchase_revenue, 0)` |
| 遞增篩選 | 僅處理比 `max(event_time)` 更新的記錄 |

### Marts 層（星狀綱要）

#### `fact_sessions` — 購物漏斗事實表

**物化方式**：遞增模型（unique_key：`session_id`）

每一列代表一個用戶工作階段，包含各漏斗階段的二元標記：

| 欄位 | 說明 |
|---|---|
| `session_id` | 唯一工作階段識別碼（粒度鍵）|
| `customer_id` | 用戶 pseudo ID → 關聯 `dim_customers` |
| `traffic_sk` | 代理鍵 → 關聯 `dim_traffic` |
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
| `customer_id` | 用戶 pseudo ID（主鍵）|
| `main_country` | 最常出現的國家/地區 |
| `lifetime_value` | 所有工作階段的購買總金額 |
| `total_orders` | 購買事件總次數 |

#### `dim_traffic` — 流量來源維度

透過 `dbt_utils.generate_surrogate_key(['traffic_source', 'traffic_medium'])` 生成代理鍵，便於從 `fact_sessions` 進行乾淨的 JOIN 關聯。

### 資料品質測試 — 26 項

所有模型均有 `schema.yml` 測試覆蓋，橫跨 staging 與 marts 兩層：

| 測試類型 | 數量 | 範例 |
|---|---|---|
| `unique` | 3 | `session_id`、`customer_id`、`traffic_sk` |
| `not_null` | 12 | 所有主鍵、外鍵及必填欄位 |
| `accepted_values` | 8 | device_category ∈ {mobile, desktop, tablet}、漏斗標記 ∈ {0, 1} |
| `relationships` | 3 | `fact_sessions.customer_id` → `dim_customers`、`traffic_sk` → `dim_traffic` |

```
$ dbt test
Completed successfully. PASS=26 WARN=0 ERROR=0 SKIP=0
```

---

## 三、主要發現

### 購物漏斗

```
session_start  →  view_item  →  add_to_cart  →  begin_checkout  →  purchase
   104,202         19,774          2,178            4,575            1,311
                   (19.0%)         (2.1%)           (4.4%)          (1.3%)
```

> **注意**：`begin_checkout` 數量（4,575）超過 `add_to_cart`（2,178）。這是 GA4 資料的已知特性 — 有 3,532 個工作階段觸發了 `begin_checkout` 但沒有 `add_to_cart` 事件，可能因為「直接購買」流程或儲存的購物車項目未觸發 `add_to_cart` 事件。詳見 `problem_solve.ipynb`。

### 常用分析查詢

**漏斗轉換率**
```sql
SELECT
    COUNT(DISTINCT CASE WHEN is_session_start = 1 THEN session_id END) AS sessions,
    COUNT(DISTINCT CASE WHEN is_view_item     = 1 THEN session_id END) AS viewed_item,
    COUNT(DISTINCT CASE WHEN is_add_to_cart   = 1 THEN session_id END) AS added_to_cart,
    COUNT(DISTINCT CASE WHEN is_begin_checkout= 1 THEN session_id END) AS began_checkout,
    COUNT(DISTINCT CASE WHEN is_purchase      = 1 THEN session_id END) AS purchased
FROM marts.fact_sessions;
```

**各流量來源轉換率**
```sql
SELECT
    t.traffic_source,
    COUNT(DISTINCT f.session_id)                                         AS total_sessions,
    SUM(f.is_purchase)                                                   AS purchases,
    ROUND(SUM(f.is_purchase)::NUMERIC / COUNT(DISTINCT f.session_id), 4) AS cvr
FROM marts.fact_sessions f
JOIN marts.dim_traffic t ON f.traffic_sk = t.traffic_sk
GROUP BY 1
ORDER BY cvr DESC;
```

**高價值顧客分群**
```sql
SELECT customer_id, main_country, lifetime_value, total_orders
FROM marts.dim_customers
WHERE total_orders >= 2
ORDER BY lifetime_value DESC
LIMIT 20;
```

---

## 專案結構

```
02_Ecommerce_Customer_Journey/
│
├── data/
│   └── raw_ga4_events.csv                  # 提取的 GA4 事件（2020 年 11 月）
│
├── scripts/
│   ├── create_table.sql                    # PostgreSQL raw 綱要建立
│   └── copy_raw.sql                        # 載入 CSV 至 raw.ga4_events
│
├── ga4_dbt/                                # dbt 專案根目錄
│   ├── dbt_project.yml                     # 專案設定（marts = table）
│   ├── packages.yml                        # dbt_utils 套件依賴
│   ├── models/
│   │   ├── staging/
│   │   │   ├── _sources.yml                # 來源定義（raw.ga4_events）
│   │   │   ├── schema.yml                  # Staging 欄位測試（5 項）
│   │   │   └── stg_ga4_events.sql          # 遞增 staging 模型
│   │   └── marts/
│   │       ├── schema.yml                  # Marts 欄位測試（21 項）
│   │       ├── fact_sessions.sql           # 漏斗事實表（遞增）
│   │       ├── dim_customers.sql           # 顧客 LTV 維度（table）
│   │       └── dim_traffic.sql             # 流量來源維度（table）
│   ├── tests/                              # 自訂資料測試
│   ├── macros/                             # dbt 巨集
│   └── analyses/                           # 臨時分析 SQL
│
├── dashboard/
│   ├── Journey.pbix                        # Power BI 儀表板檔案
│   └── Journey.pdf                         # 儀表板匯出（預覽用）
│
├── screenshot/
│   ├── bi01.png                            # 第 1 頁 — 總覽
│   ├── bi02.png                            # 第 2 頁 — 轉換與流量
│   ├── bi03.png                            # 第 3 頁 — 顧客分群
│   └── schema.png                          # dbt 模型血緣圖
│
├── problem_solve.ipynb                     # 資料異常調查與筆記
├── LICENSE                                 # MIT 授權條款
├── README.md                               # English 文件
├── README.zh-TW.md                         # 繁體中文文件
└── README.zh-CN.md                         # 简体中文文档
```

---

## 如何重現本專案

**前置需求**：Google Cloud 帳戶（BigQuery 存取）、PostgreSQL 14+、Python 3.9+、dbt-postgres、Power BI Desktop

### 步驟 1 — 從 BigQuery 提取

在 BigQuery Console 執行上述提取 SQL，並將結果匯出為 CSV。

### 步驟 2 — 載入 PostgreSQL

```bash
psql -U postgres -f scripts/create_table.sql
# 編輯 scripts/copy_raw.sql，設定你的本機 CSV 路徑，然後：
psql -U postgres -f scripts/copy_raw.sql
```

### 步驟 3 — 執行 dbt

```bash
cd ga4_dbt
pip install dbt-postgres     # 若尚未安裝
dbt deps                     # 安裝 dbt_utils
dbt run                      # 建立所有模型
dbt test                     # 執行 26 項資料品質測試
```

### 步驟 4 — 開啟 Power BI

1. 在 Power BI Desktop 開啟 `dashboard/Journey.pbix`
2. 更新 PostgreSQL 連線至你的本機伺服器
3. 重新整理資料 — 儀表板會從 `marts` 綱要讀取資料

---

## 已知問題與設計決策

| 項目 | 說明 |
|---|---|
| `begin_checkout` > `add_to_cart` | 3,532 個工作階段跳過了 `add_to_cart` — 這是 GA4 資料特性，非 Bug。詳見 `problem_solve.ipynb`。|
| `stg_ga4_events` 使用遞增模型 | 為大量 GA4 事件日誌選擇效能優先方案。代價：修改轉換邏輯時需執行 `--full-refresh`。|
| `dbt_project.yml` 僅使用英文註解 | Windows 繁體中文系統（cp950 編碼）無法解析此檔案中的 UTF-8 中文字元。|
| 流量來源 `(direct)` 對應為 `Direct` | 保留為獨立類別 — 直接流量（輸入網址/書籤）具有分析意義，與 `(data deleted)` 不同。|

---

## 授權條款

本專案採用 [MIT License](./LICENSE) 授權。
