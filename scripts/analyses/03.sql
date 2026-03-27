SELECT
    t.traffic_source,
    t.traffic_medium,
    f.device_category,
    COUNT(DISTINCT f.session_id)                                              AS total_sessions,
    SUM(f.is_view_item)                                                       AS view_item,
    SUM(f.is_add_to_cart)                                                     AS add_to_cart,
    SUM(f.is_begin_checkout)                                                  AS begin_checkout,
    SUM(f.is_purchase)                                                        AS purchases,
    ROUND(SUM(f.is_purchase)::NUMERIC / NULLIF(COUNT(DISTINCT f.session_id), 0) * 100, 2) AS conversion_rate_pct,
    ROUND(SUM(f.session_revenue)::NUMERIC, 2)                                 AS total_revenue
FROM marts.fact_sessions f
LEFT JOIN marts.dim_traffic t ON f.traffic_sk = t.traffic_sk
GROUP BY t.traffic_source, t.traffic_medium, f.device_category
ORDER BY total_sessions DESC;