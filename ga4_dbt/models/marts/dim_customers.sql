-- 解決「找出高價值顧客」目標

SELECT 
    user_pseudo_id AS customer_id,
    MAX(country) AS main_country,
    SUM(purchase_revenue) AS lifetime_value,
    SUM(CASE WHEN event_name = 'purchase' THEN 1 ELSE 0 END) AS total_orders
FROM {{ ref('stg_ga4_events') }}
GROUP BY 1
