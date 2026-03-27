WITH cust AS (
    SELECT
        customer_id,
        main_country,
        lifetime_value,
        total_orders,
        NTILE(4) OVER (ORDER BY lifetime_value) AS ltv_sort   -- 1~4，4 為最高 LTV
    FROM marts.dim_customers
),
cust_seg AS (
    SELECT
        customer_id,
        main_country,
        lifetime_value,
        total_orders,
        ltv_sort,
        CASE
            WHEN ltv_sort = 4 THEN 'VIP'
            WHEN ltv_sort = 3 THEN 'High'
            WHEN ltv_sort = 2 THEN 'Mid'
            ELSE 'Low'
        END AS ltv_segment
    FROM cust
)
SELECT
    c.ltv_segment,
    c.ltv_sort,
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
FROM cust_seg c
LEFT JOIN marts.fact_sessions f
       ON c.customer_id = f.customer_id
GROUP BY
    c.ltv_segment,
    c.ltv_sort
ORDER BY
    c.ltv_sort;