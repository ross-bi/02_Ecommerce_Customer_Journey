CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE raw.ga4_events (
    event_date INT,
    event_time TIMESTAMP,
    event_name VARCHAR(50),
    user_pseudo_id VARCHAR(100),
    session_id BIGINT,
    device_category VARCHAR(50),
    operating_system VARCHAR(50),
    country VARCHAR(100),
    city VARCHAR(100),
    traffic_source VARCHAR(100),
    traffic_medium VARCHAR(100),
    purchase_revenue NUMERIC,
    total_item_quantity INT
);
