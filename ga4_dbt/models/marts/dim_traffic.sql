-- 解決「分析流量來源」目標

SELECT DISTINCT
    {{ dbt_utils.generate_surrogate_key(['traffic_source', 'traffic_medium']) }} AS traffic_sk,
    traffic_source,
    traffic_medium
FROM {{ ref('stg_ga4_events') }}
