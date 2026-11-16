import duckdb

from erp_platform.config import Settings

MARTS = [
    "dim_date",
    "dim_customer",
    "dim_dealer",
    "dim_part",
    "fct_sales",
    "fct_orders",
    "fx_rates_daily",
    "fct_inventory_daily",
    "rpt_stockout_risk",
]


def query(settings: Settings, sql: str) -> list[tuple]:
    conn = duckdb.connect(settings.warehouse_path, read_only=True)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def mart_counts(settings: Settings) -> dict[str, int]:
    return {m: query(settings, f"select count(*) from marts.{m}")[0][0] for m in MARTS}
