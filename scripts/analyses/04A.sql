SELECT
    c.main_country,
    ROUND(AVG(c.lifetime_value)::NUMERIC, 2)                                  AS avg_ltv,
    ROUND(AVG(c.total_orders)::NUMERIC, 2)                                    AS avg_total_orders,
    COUNT(DISTINCT f.session_id)                                              AS total_sessions,
    SUM(f.is_view_item)                                                       AS view_item,
    SUM(f.is_add_to_cart)                                                     AS add_to_cart,
    SUM(f.is_begin_checkout)                                                  AS begin_checkout,
    SUM(f.is_purchase)                                                        AS purchases,
    ROUND(SUM(f.is_purchase)::NUMERIC / NULLIF(COUNT(DISTINCT f.session_id), 0) * 100, 2) AS conversion_rate_pct,
    ROUND(SUM(f.session_revenue)::NUMERIC, 2)                                 AS total_revenue,
    ROUND(SUM(f.session_revenue)::NUMERIC / NULLIF(SUM(f.is_purchase), 0), 2) AS avg_order_value
FROM marts.dim_customers   AS c
LEFT JOIN marts.fact_sessions AS f
       ON c.customer_id = f.customer_id
GROUP BY
    c.main_country
ORDER BY
    total_revenue DESC;