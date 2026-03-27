SELECT
    c.customer_id,
    c.main_country,
    c.lifetime_value,
    c.total_orders,
    COUNT(DISTINCT f.session_id)                                              AS total_sessions,
    SUM(f.is_purchase)                                                        AS total_purchases,
    ROUND(SUM(f.session_revenue)::NUMERIC, 2)                                 AS total_revenue,
    ROUND(
        SUM(f.is_purchase)::NUMERIC
        / NULLIF(COUNT(DISTINCT f.session_id), 0) * 100
    , 2)                                                                      AS conversion_rate_pct
FROM marts.dim_customers   AS c
LEFT JOIN marts.fact_sessions AS f
       ON c.customer_id = f.customer_id
GROUP BY
    c.customer_id,
    c.main_country,
    c.lifetime_value,
    c.total_orders
ORDER BY
    c.lifetime_value DESC
LIMIT 200;