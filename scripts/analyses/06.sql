SELECT
    t.traffic_source,
    t.traffic_medium,
    c.main_country,
    COUNT(DISTINCT f.session_id)                    AS sessions,
    SUM(f.is_purchase)                              AS purchases,
    ROUND(SUM(f.session_revenue)::NUMERIC, 2)       AS revenue,
    ROUND(AVG(c.lifetime_value)::NUMERIC, 2)        AS avg_ltv,
    ROUND(AVG(c.total_orders)::NUMERIC, 2)          AS avg_total_orders
FROM marts.fact_sessions f
LEFT JOIN marts.dim_customers c
       ON f.customer_id = c.customer_id
LEFT JOIN marts.dim_traffic  t
       ON f.traffic_sk  = t.traffic_sk
GROUP BY
    t.traffic_source,
    t.traffic_medium,
    c.main_country
ORDER BY
    revenue DESC;