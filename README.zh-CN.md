[![繁體中文](https://img.shields.io/badge/繁體中文-點擊查看-blue?style=for-the-badge)](README.zh-TW.md)
&nbsp;&nbsp;
[![简体中文](https://img.shields.io/badge/简体中文-点击查看-blue?style=for-the-badge)](README.zh-CN.md)

# 电商顾客旅程分析

**BigQuery · PostgreSQL · dbt · Power BI**

---

## 专案概述

本项目使用 [GA4 Obfuscated Sample E-Commerce 数据集](https://console.cloud.google.com/bigquery?p=bigquery-public-data&d=ga4_obfuscated_sample_ecommerce)（Google 发布的 BigQuery 公开数据集，真实电商数据经过混淆处理），进行端对端的电商顾客旅程分析。

目标是了解**顾客如何在购物漏斗中移动**、识别高价值客群，以及分析各流量来源、装置与地区的转换率表现。

### 涵盖范畴

- 从 **BigQuery** 提取 GA4 事件资料并加载 **PostgreSQL**
- 建立分层 **dbt** 数据转换流程（staging → marts）
- 建模购物漏斗事实表与顾客维度表，供 Power BI 分析使用
- 分析转换率、会话行为及顾客终身价值

---

## 数据集

| 项目 | 说明 |
|---|---|
| 来源 | [BigQuery 公开资料 — GA4 Obfuscated Sample E-Commerce](https://console.cloud.google.com/bigquery?p=bigquery-public-data&d=ga4_obfuscated_sample_ecommerce) |
| 时间范围 | 2020 年 11 月（共 30 天）|
| 撷取事件 | `session_start`、`view_item`、`add_to_cart`、`begin_checkout`、`purchase` |
| 主要字段 | 事件日期、事件时间、事件名称、用户 ID、会话 ID、装置类别、国家/地区、流量来源、购买金额 |

---

## 工具与技术

| 工具 | 用途 |
|---|---|
| BigQuery | 源数据提取（GA4 公开数据集）|
| PostgreSQL | 数据仓储 — 储存原始及转换后的数据表 |
| dbt | 数据转换流程（staging + marts 分层）|
| Power BI | 漏斗可视化与顾客分群仪表板 |
| GitHub | 版本控制与文件记录 |

---

## 架构概览

```
BigQuery（GA4 公开资料）
        │
        ▼  SQL 提取 → CSV 汇出
PostgreSQL: raw.ga4_events
        │
        ▼  dbt staging 层
stg_ga4_events          ← 清理、正规化的事件数据（递增模型）
        │
        ▼  dbt marts 层
fact_sessions           ← 会话层级漏斗标记 + 收入（递增模型）
dim_customers           ← 顾客终身价值 + 订单数量
dim_traffic             ← 流量来源/媒介维度表
        │
        ▼
Power BI 仪表板
```

---

## 一、资料提取（BigQuery → PostgreSQL）

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

提取的数据加载 PostgreSQL 的 `raw.ga4_events`，供 dbt 后续处理。

---

## 二、dbt 数据转换流程

### Staging 层 — `stg_ga4_events`

**物化方式**：递增模型（unique_key：`session_id`）

套用的转换：
- 将装置及地区字段的 `(not set)` 值设为 NULL
- 正规化噪声流量来源（`(data deleted)`、`(direct)`、`<Other>` → `Unknown`）
- 购买金额及数量的 NULL 补 0（COALESCE）
- 递增筛选：仅处理比现有数据库中最新 `event_time` 更新的记录

### Marts 层

#### `fact_sessions` — 购物漏斗事实表

**物化方式**：递增模型（unique_key：`session_id`）

每一列代表一个用户会话，包含各漏斗阶段的二元标记：

| 字段 | 说明 |
|---|---|
| `session_id` | 唯一会话标识符 |
| `customer_id` | 用户 pseudo ID |
| `traffic_sk` | 代理键（流量来源 + 媒介）|
| `device_category` | 此会话的装置类型 |
| `is_session_start` | 1 = 会话已开始 |
| `is_view_item` | 1 = 已浏览商品 |
| `is_add_to_cart` | 1 = 已加入购物车 |
| `is_begin_checkout` | 1 = 已开始结账 |
| `is_purchase` | 1 = 已完成购买 |
| `session_revenue` | 此会话的购买总金额 |

#### `dim_customers` — 顾客终身价值维度

| 字段 | 说明 |
|---|---|
| `customer_id` | 用户 pseudo ID |
| `main_country` | 最常出现的国家/地区 |
| `lifetime_value` | 所有会话的购买总金额 |
| `total_orders` | 购买事件总次数 |

#### `dim_traffic` — 流量来源维度

透过 `dbt_utils.generate_surrogate_key(['traffic_source', 'traffic_medium'])` 生成代理键，便于从 `fact_sessions` 进行干净的 JOIN 关联。

---

## 三、主要分析

### 漏斗转换率
```sql
SELECT
    COUNT(DISTINCT CASE WHEN is_session_start = 1 THEN session_id END) AS sessions,
    COUNT(DISTINCT CASE WHEN is_view_item     = 1 THEN session_id END) AS viewed_item,
    COUNT(DISTINCT CASE WHEN is_add_to_cart   = 1 THEN session_id END) AS added_to_cart,
    COUNT(DISTINCT CASE WHEN is_begin_checkout= 1 THEN session_id END) AS began_checkout,
    COUNT(DISTINCT CASE WHEN is_purchase      = 1 THEN session_id END) AS purchased
FROM marts.fact_sessions;
```

### 高价值顾客分群
```sql
SELECT customer_id, main_country, lifetime_value, total_orders
FROM marts.dim_customers
WHERE total_orders >= 2
ORDER BY lifetime_value DESC
LIMIT 20;
```

### 各流量来源转换率
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

## 项目结构

```
02_Ecommerce_Customer_Journey/
│
├── data/
│   └── raw_ga4_events.csv               # 提取的 GA4 事件（2020 年 11 月）
│
├── scripts/
│   ├── create_table.sql                 # PostgreSQL raw 纲要建立
│   └── copy_raw.sql                     # 载入 CSV 至 raw.ga4_events
│
├── ga4_dbt/                             # dbt 项目根目录
│   ├── dbt_project.yml
│   ├── packages.yml                     # dbt_utils 套件依赖
│   ├── models/
│   │   ├── staging/
│   │   │   ├── _sources.yml             # 来源定义（raw.ga4_events）
│   │   │   ├── schema.yml               # 字段测试与说明
│   │   │   └── stg_ga4_events.sql       # 递增 staging 模型
│   │   └── marts/
│   │       ├── fact_sessions.sql        # 漏斗事实表（递增）
│   │       ├── dim_customers.sql        # 顾客 LTV 维度
│   │       └── dim_traffic.sql          # 流量来源维度
│   ├── tests/                           # 自定义 dbt 资料测试
│   ├── macros/                          # dbt 宏
│   └── analyses/                        # 临时分析 SQL
│
└── README.md
```

---

## 如何重现本项目

**前置需求**：Google Cloud 账户（BigQuery 存取）、PostgreSQL 14+、dbt-postgres、Power BI Desktop

1. **从 BigQuery 提取**：在 BigQuery 执行上述提取 SQL 并汇出为 CSV
2. **载入 PostgreSQL**：执行 `scripts/create_table.sql`，再执行 `scripts/copy_raw.sql`
3. **执行 dbt**：进入 `ga4_dbt/` 目录并执行：
   ```bash
   dbt deps       # 安装 dbt_utils
   dbt run        # 建立所有模型
   dbt test       # 执行数据质量测试
   ```
4. **开启 Power BI**：连接至 PostgreSQL 的 `marts` 纲要

---

## 授权条款

本项目采用 [MIT LICENSE](./LICENSE)授权。


