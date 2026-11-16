import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import streamlit as st

from erp_platform.config import load_dashboard_settings
from erp_platform.publish import LAST_SUCCESS_FILE, PUBLISHED_MARTS

# One colour: every chart here shows a single series, so colour carries no identity.
BAR_COLOUR = "#2a6fdb"

Q1 = """
select dealer_code, dealer_name, region, part_number, part_name,
       quantity_on_hand, units_sold_28d, days_of_cover
from rpt_stockout_risk
where is_at_risk
order by days_of_cover, dealer_code, part_number
"""

# The region is the one the dealer had when the order was placed.
Q2 = """
select dealers.region, dealers.dealer_code, count(*) as orders,
       round(avg(orders.hours_to_ship), 1) as avg_hours_to_ship,
       round(avg(orders.hours_to_deliver), 1) as avg_hours_to_deliver
from fct_orders as orders
inner join dim_dealer as dealers on orders.dealer_key = dealers.dealer_key
where orders.order_status <> 'cancelled'
group by dealers.region, dealers.dealer_code
order by dealers.region, dealers.dealer_code
"""

Q3 = """
select parts.machine_model, sum(sales.amount_jpy) as sales_jpy
from fct_sales as sales
inner join dim_part as parts on sales.part_key = parts.part_key
where sales.order_status <> 'cancelled'
group by parts.machine_model
order by sales_jpy desc
"""

RECONCILIATION = """
select run_id, count(*) as metrics,
       count(*) filter (where is_match) as matched,
       bool_and(is_match) as all_match
from reconciliation_runs
group by run_id
order by run_id desc
limit 20
"""


def open_serving(serving_dir: Path) -> duckdb.DuckDBPyConnection:
    """An in-memory connection with one view per published file; the warehouse is never opened."""
    conn = duckdb.connect()
    for mart in PUBLISHED_MARTS:
        path = (serving_dir / f"{mart}.parquet").as_posix()
        conn.execute(f"create view {mart} as select * from read_parquet('{path}')")
    return conn


def show_last_run(serving_dir: Path, interval_minutes: int) -> None:
    marker = serving_dir / LAST_SUCCESS_FILE
    if not marker.exists():
        st.warning("No successful run recorded yet.")
        return
    finished_at = datetime.fromisoformat(json.loads(marker.read_text())["finished_at"]).astimezone(
        UTC
    )
    age = datetime.now(UTC) - finished_at
    st.metric("Last successful run (UTC)", finished_at.strftime("%Y-%m-%d %H:%M:%S"))
    if age > 2 * timedelta(minutes=interval_minutes):
        st.warning(
            f"The last successful run finished {int(age.total_seconds() // 60)} minutes ago; "
            f"runs are scheduled every {interval_minutes} minutes. The data below is stale."
        )


st.set_page_config(page_title="ERP parts and sales", layout="wide")
st.title("ERP parts and sales")
st.caption("Synthetic data. Published from the warehouse by `erp publish`.")

settings = load_dashboard_settings()
serving_dir = Path(settings.serving_dir)
show_last_run(serving_dir, settings.schedule_interval_minutes)

missing = [m for m in PUBLISHED_MARTS if not (serving_dir / f"{m}.parquet").exists()]
if missing:
    st.info(f"Nothing published yet in {serving_dir}: run `erp publish`.")
    st.stop()

conn = open_serving(serving_dir)

st.subheader("Q1. Which dealers risk running out of a part within seven days?")
st.dataframe(conn.execute(Q1).df(), hide_index=True, width="stretch")

st.subheader("Q2. How long does order fulfilment take, per dealer and per region?")
st.dataframe(conn.execute(Q2).df(), hide_index=True, width="stretch")

st.subheader("Q3. Parts sales per machine model (JPY)")
# Streamlit sorts a bar chart's categories alphabetically unless told which column to sort by.
st.bar_chart(
    conn.execute(Q3).df(),
    x="machine_model",
    y="sales_jpy",
    x_label="Machine model",
    y_label="Sales (JPY)",
    color=BAR_COLOUR,
    horizontal=True,
    sort="-sales_jpy",
)

st.subheader("Reconciliation history (newest 20 runs)")
st.dataframe(conn.execute(RECONCILIATION).df(), hide_index=True, width="stretch")
