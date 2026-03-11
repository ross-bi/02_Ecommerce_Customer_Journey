-- models/staging/stg_ga4_events.sql

{{ config(
    materialized='incremental',
    unique_key='session_id'
) }}

WITH raw_data AS (
    SELECT * FROM {{ source('raw', 'ga4_events') }}
)
SELECT 
    event_date,
    event_time,
    event_name,
    user_pseudo_id,
    session_id,
    
    -- 清理裝置與地區的 (not set) 
    NULLIF(device_category, '(not set)') AS device_category,
    NULLIF(operating_system, '(not set)') AS operating_system,
    NULLIF(country, '(not set)') AS country,
    NULLIF(city, '(not set)') AS city,
    
    -- 清理流量來源的雜訊
    CASE WHEN traffic_source IN ('(data deleted)', '(direct)', '<Other>') THEN 'Unknown' ELSE traffic_source END AS traffic_source,
    CASE WHEN traffic_medium IN ('(data deleted)', '(none)') THEN 'Unknown' ELSE traffic_medium END AS traffic_medium,
    
    -- 確保金額若是 null 就補 0
    COALESCE(purchase_revenue, 0) AS purchase_revenue,
    COALESCE(total_item_quantity, 0) AS total_item_quantity

FROM raw_data

{% if is_incremental() %}
  -- 只有當這是後續更新時，才只抓取比現有資料庫中最新的日期還要新的資料
  WHERE event_time > (SELECT max(event_time) FROM {{ this }})
{% endif %}