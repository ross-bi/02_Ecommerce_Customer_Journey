-- Update the file path below to match your local environment before running.
-- 在執行之前，請先更新下面的檔案路徑，使其符合你本地環境。
-- Example (Windows): 'C:/Users/YourName/Downloads/raw_ga4_events.csv'
-- Example (Mac/Linux): '/home/yourname/data/raw_ga4_events.csv'

COPY raw.ga4_events
FROM '/your/path/to/raw_ga4_events.csv'
DELIMITER ',' CSV HEADER;
