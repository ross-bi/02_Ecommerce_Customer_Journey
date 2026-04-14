SELECT
    COUNT(DISTINCT session_id)                                          AS total_sessions,
    SUM(is_session_start)                                               AS session_starts,
    SUM(is_view_item)                                                   AS view_item,
    SUM(is_add_to_cart)                                                 AS add_to_cart,
    SUM(is_begin_checkout)                                              AS begin_checkout,
    SUM(is_purchase)                                                    AS purchases,

    ROUND(SUM(is_view_item)::NUMERIC    / NULLIF(COUNT(DISTINCT session_id), 0) * 100, 2) AS view_rate_pct,
    ROUND(SUM(is_add_to_cart)::NUMERIC  / NULLIF(SUM(is_view_item), 0)        * 100, 2) AS add_to_cart_rate_pct,
    ROUND(SUM(is_begin_checkout)::NUMERIC / NULLIF(SUM(is_add_to_cart), 0)    * 100, 2) AS checkout_rate_pct,
    ROUND(SUM(is_purchase)::NUMERIC     / NULLIF(SUM(is_begin_checkout), 0)   * 100, 2) AS purchase_rate_pct,
    ROUND(SUM(is_purchase)::NUMERIC     / NULLIF(COUNT(DISTINCT session_id), 0) * 100, 2) AS overall_conversion_pct,

    ROUND(SUM(session_revenue)::NUMERIC, 2)                            AS total_revenue
FROM marts.fact_sessions;