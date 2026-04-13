"""
Data Quality Check — 02_Ecommerce_Customer_Journey
====================================================
Connects to PostgreSQL and validates the three dbt mart tables:
  - raw.ga4_events        (source layer)
  - marts.fact_sessions   (fact table)
  - marts.dim_customers   (dimension table)
  - marts.dim_traffic     (dimension table)

Checks performed:
  1. Row count & null rate per table
  2. Primary key uniqueness
  3. Referential integrity  (fact → dim joins)
  4. Funnel logic sanity   (begin_checkout >= purchase)
  5. Revenue sanity        (no negative session_revenue)
  6. Export summary report to data_quality_report.csv

Usage:
  python scripts/data_quality_check.py

Requirements (already in requirements.txt):
  psycopg2-binary, pandas
  pip install pandas  (not in requirements.txt — add if needed)

Connection:
  Set environment variables or edit DB_CONFIG below.
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""

import os
import sys
import datetime
import psycopg2
import pandas as pd
from psycopg2 import sql

# ── Connection config ────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5432")),
    "dbname":   os.getenv("DB_NAME",     "ecommerce"),
    "user":     os.getenv("DB_USER",     "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

# ── Output path ──────────────────────────────────────────────────────────────
REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "data_quality_report.csv")


# ── Helpers ──────────────────────────────────────────────────────────────────
def get_conn():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except psycopg2.OperationalError as e:
        print(f"[ERROR] Cannot connect to PostgreSQL: {e}")
        sys.exit(1)


def run_query(conn, query: str) -> pd.DataFrame:
    return pd.read_sql_query(query, conn)


def add_result(results: list, check_name: str, table: str,
               status: str, value, threshold=None, note: str = ""):
    results.append({
        "check_name":  check_name,
        "table":       table,
        "status":      status,        # PASS / WARN / FAIL
        "value":       value,
        "threshold":   threshold,
        "note":        note,
        "run_at":      datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


# ── Check functions ──────────────────────────────────────────────────────────

def check_row_counts(conn, results):
    """Ensure each mart table has rows (not empty)."""
    tables = [
        "raw.ga4_events",
        "marts.fact_sessions",
        "marts.dim_customers",
        "marts.dim_traffic",
    ]
    for tbl in tables:
        df = run_query(conn, f"SELECT COUNT(*) AS cnt FROM {tbl};")
        cnt = int(df["cnt"].iloc[0])
        status = "PASS" if cnt > 0 else "FAIL"
        add_result(results, "row_count", tbl, status, cnt,
                   threshold=">0",
                   note="Table is empty!" if cnt == 0 else "")
        print(f"  [row_count]  {tbl:<35} {cnt:>10,} rows  →  {status}")


def check_null_rates(conn, results):
    """Check NULL rates for critical columns."""
    checks = [
        # (table, column, max_allowed_null_pct)
        ("marts.fact_sessions",  "session_id",       0.0),
        ("marts.fact_sessions",  "customer_id",      0.0),
        ("marts.fact_sessions",  "traffic_sk",       5.0),
        ("marts.fact_sessions",  "session_revenue",  0.0),
        ("marts.dim_customers",  "customer_id",      0.0),
        ("marts.dim_customers",  "lifetime_value",   1.0),
        ("marts.dim_traffic",    "traffic_sk",       0.0),
        ("marts.dim_traffic",    "traffic_source",  10.0),
        ("raw.ga4_events",       "user_pseudo_id",   0.0),
        ("raw.ga4_events",       "event_name",       0.0),
    ]
    for tbl, col, max_pct in checks:
        df = run_query(conn, f"""
            SELECT
                COUNT(*)                                         AS total,
                SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END)  AS nulls
            FROM {tbl};
        """)
        total = int(df["total"].iloc[0])
        nulls = int(df["nulls"].iloc[0])
        null_pct = round(nulls / total * 100, 2) if total > 0 else 0.0
        status = "PASS" if null_pct <= max_pct else "FAIL"
        add_result(results, "null_rate", tbl, status,
                   f"{null_pct}%",
                   threshold=f"<={max_pct}%",
                   note=f"column: {col}  nulls: {nulls:,}/{total:,}")
        flag = "✓" if status == "PASS" else "✗"
        print(f"  [null_rate]  {tbl}.{col:<25} null={null_pct}%  ({flag})")


def check_pk_uniqueness(conn, results):
    """Verify primary keys are unique."""
    pk_checks = [
        ("marts.fact_sessions", "session_id"),
        ("marts.dim_customers", "customer_id"),
        ("marts.dim_traffic",   "traffic_sk"),
    ]
    for tbl, pk in pk_checks:
        df = run_query(conn, f"""
            SELECT COUNT(*) AS total, COUNT(DISTINCT {pk}) AS unique_cnt
            FROM {tbl};
        """)
        total      = int(df["total"].iloc[0])
        unique_cnt = int(df["unique_cnt"].iloc[0])
        dupes      = total - unique_cnt
        status     = "PASS" if dupes == 0 else "FAIL"
        add_result(results, "pk_uniqueness", tbl, status,
                   dupes, threshold="0 duplicates",
                   note=f"pk: {pk}  duplicates: {dupes:,}")
        print(f"  [pk_unique]  {tbl}.{pk:<25} dupes={dupes:,}  →  {status}")


def check_referential_integrity(conn, results):
    """Check fact → dim foreign key integrity."""
    fk_checks = [
        (
            "fact→dim_customers",
            """
            SELECT COUNT(*) AS orphans
            FROM   marts.fact_sessions f
            LEFT JOIN marts.dim_customers c ON f.customer_id = c.customer_id
            WHERE  c.customer_id IS NULL;
            """,
        ),
        (
            "fact→dim_traffic",
            """
            SELECT COUNT(*) AS orphans
            FROM   marts.fact_sessions f
            LEFT JOIN marts.dim_traffic t ON f.traffic_sk = t.traffic_sk
            WHERE  t.traffic_sk IS NULL;
            """,
        ),
    ]
    for name, query in fk_checks:
        df      = run_query(conn, query)
        orphans = int(df["orphans"].iloc[0])
        status  = "PASS" if orphans == 0 else "WARN"
        add_result(results, "referential_integrity", "marts.fact_sessions",
                   status, orphans, threshold="0 orphans", note=name)
        print(f"  [ref_integ]  {name:<35} orphans={orphans:,}  →  {status}")


def check_funnel_logic(conn, results):
    """
    Sanity check: sessions with purchase but no begin_checkout should be 0.
    Also: begin_checkout count should be >= purchase count overall.
    """
    # Check 1: purchase without checkout
    df = run_query(conn, """
        SELECT COUNT(*) AS cnt
        FROM   marts.fact_sessions
        WHERE  is_purchase = 1 AND is_begin_checkout = 0;
    """)
    cnt    = int(df["cnt"].iloc[0])
    status = "PASS" if cnt == 0 else "WARN"
    add_result(results, "funnel_logic", "marts.fact_sessions", status, cnt,
               threshold="0",
               note="Sessions with purchase but no begin_checkout")
    print(f"  [funnel]     purchase_without_checkout={cnt:,}  →  {status}")

    # Check 2: total begin_checkout >= total purchase
    df2 = run_query(conn, """
        SELECT SUM(is_begin_checkout) AS co, SUM(is_purchase) AS pur
        FROM   marts.fact_sessions;
    """)
    co  = int(df2["co"].iloc[0]  or 0)
    pur = int(df2["pur"].iloc[0] or 0)
    status2 = "PASS" if co >= pur else "FAIL"
    add_result(results, "funnel_logic", "marts.fact_sessions", status2,
               f"checkout={co:,} purchase={pur:,}",
               threshold="checkout >= purchase",
               note="Aggregate funnel direction check")
    print(f"  [funnel]     checkout={co:,}  purchase={pur:,}  →  {status2}")


def check_revenue_sanity(conn, results):
    """No negative session_revenue; revenue should match sum of purchase rows."""
    # Negative revenue
    df = run_query(conn, """
        SELECT COUNT(*) AS cnt
        FROM   marts.fact_sessions
        WHERE  session_revenue < 0;
    """)
    cnt    = int(df["cnt"].iloc[0])
    status = "PASS" if cnt == 0 else "FAIL"
    add_result(results, "revenue_sanity", "marts.fact_sessions", status, cnt,
               threshold="0", note="Rows with negative session_revenue")
    print(f"  [revenue]    negative_revenue_rows={cnt:,}  →  {status}")

    # Revenue only on purchase sessions
    df2 = run_query(conn, """
        SELECT COUNT(*) AS cnt
        FROM   marts.fact_sessions
        WHERE  session_revenue > 0 AND is_purchase = 0;
    """)
    cnt2    = int(df2["cnt"].iloc[0])
    status2 = "PASS" if cnt2 == 0 else "WARN"
    add_result(results, "revenue_sanity", "marts.fact_sessions", status2, cnt2,
               threshold="0",
               note="Revenue > 0 but is_purchase = 0 (possible data anomaly)")
    print(f"  [revenue]    revenue_without_purchase={cnt2:,}  →  {status2}")


def check_event_coverage(conn, results):
    """Verify all 5 expected funnel events exist in raw.ga4_events."""
    expected_events = {
        "session_start", "view_item", "add_to_cart", "begin_checkout", "purchase"
    }
    df     = run_query(conn, "SELECT DISTINCT event_name FROM raw.ga4_events;")
    actual = set(df["event_name"].tolist())
    missing = expected_events - actual
    status  = "PASS" if not missing else "FAIL"
    add_result(results, "event_coverage", "raw.ga4_events", status,
               len(actual), threshold=f"{len(expected_events)} events",
               note=f"Missing: {missing}" if missing else "All funnel events present")
    print(f"  [events]     funnel_events_found={len(actual)}  missing={missing or 'none'}  →  {status}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print(" Data Quality Check — 02_Ecommerce_Customer_Journey")
    print(f" Run at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    conn    = get_conn()
    results = []

    print("\n── 1. Row Counts ───────────────────────────────────────────")
    check_row_counts(conn, results)

    print("\n── 2. Null Rates ───────────────────────────────────────────")
    check_null_rates(conn, results)

    print("\n── 3. Primary Key Uniqueness ───────────────────────────────")
    check_pk_uniqueness(conn, results)

    print("\n── 4. Referential Integrity ────────────────────────────────")
    check_referential_integrity(conn, results)

    print("\n── 5. Funnel Logic ─────────────────────────────────────────")
    check_funnel_logic(conn, results)

    print("\n── 6. Revenue Sanity ───────────────────────────────────────")
    check_revenue_sanity(conn, results)

    print("\n── 7. Event Coverage ───────────────────────────────────────")
    check_event_coverage(conn, results)

    conn.close()

    # ── Summary ──────────────────────────────────────────────────────────────
    df_report = pd.DataFrame(results)
    total  = len(df_report)
    passed = (df_report["status"] == "PASS").sum()
    warned = (df_report["status"] == "WARN").sum()
    failed = (df_report["status"] == "FAIL").sum()

    print("\n" + "=" * 60)
    print(f" SUMMARY:  {passed} PASS  |  {warned} WARN  |  {failed} FAIL  (total {total})")
    print("=" * 60)

    if failed > 0:
        print("\n[FAIL] The following checks require immediate attention:")
        fail_df = df_report[df_report["status"] == "FAIL"][["check_name", "table", "value", "note"]]
        print(fail_df.to_string(index=False))

    if warned > 0:
        print("\n[WARN] The following checks need investigation:")
        warn_df = df_report[df_report["status"] == "WARN"][["check_name", "table", "value", "note"]]
        print(warn_df.to_string(index=False))

    # Export CSV report
    report_path = os.path.abspath(REPORT_PATH)
    df_report.to_csv(report_path, index=False, encoding="utf-8-sig")
    print(f"\n[INFO] Full report saved to: {report_path}")

    # Exit with non-zero code if any FAIL (useful for CI pipelines)
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
