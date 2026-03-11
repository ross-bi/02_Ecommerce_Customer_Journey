-- 用來畫「漏斗圖」的核心事實表

{{ config(
    materialized='incremental',
    unique_key='session_id'
) }}

SELECT 
    session_id,
    user_pseudo_id AS customer_id,
    {{ dbt_utils.generate_surrogate_key(['traffic_source', 'traffic_medium']) }} AS traffic_sk,
    MAX(device_category) AS device_category,
    
    -- 判斷這個工作階段是否有觸發各漏斗階段
    MAX(CASE WHEN event_name = 'session_start' THEN 1 ELSE 0 END) AS is_session_start,
    MAX(CASE WHEN event_name = 'view_item' THEN 1 ELSE 0 END) AS is_view_item,
    MAX(CASE WHEN event_name = 'add_to_cart' THEN 1 ELSE 0 END) AS is_add_to_cart,
    MAX(CASE WHEN event_name = 'begin_checkout' THEN 1 ELSE 0 END) AS is_begin_checkout,
    MAX(CASE WHEN event_name = 'purchase' THEN 1 ELSE 0 END) AS is_purchase,
    
    -- 紀錄最終金額
    SUM(purchase_revenue) AS session_revenue

FROM {{ ref('stg_ga4_events') }}
GROUP BY 1, 2, 3

{% if is_incremental() %}
  -- 只有當這是後續更新時，才只抓取比現有資料庫中最新的日期還要新的資料
  WHERE event_time > (SELECT max(event_time) FROM {{ this }})
{% endif %}