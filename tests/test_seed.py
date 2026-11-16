from decimal import Decimal

from conftest import temp_database

from erp_platform.config import Settings
from erp_platform.db import connect
from erp_platform.erp.seed import seed
from erp_platform.erp.simulate import FX_PER_JPY, MAX_DISCOUNT

TABLES = ["dealers", "parts", "customers", "sales_orders", "order_lines"]


def count_rows(settings: Settings) -> dict[str, int]:
    with connect(settings) as conn:
        return {t: conn.execute(f"select count(*) from erp.{t}").fetchone()[0] for t in TABLES}


def test_row_counts(seeded_template: Settings) -> None:
    with connect(seeded_template) as conn:
        per_country = dict(
            conn.execute("select country_code, count(*) from erp.dealers group by 1").fetchall()
        )
        models = conn.execute("select count(distinct machine_model) from erp.parts").fetchone()
        statuses = {r[0] for r in conn.execute("select status from erp.sales_orders")}
    counts = count_rows(seeded_template)
    assert per_country == {"JP": 10, "ID": 10, "TH": 10}
    assert counts["dealers"] == 30
    assert counts["parts"] == 500
    assert models == (8,)
    assert counts["customers"] == 2000
    assert counts["sales_orders"] > 0
    assert counts["order_lines"] >= counts["sales_orders"]
    assert statuses == {"placed", "confirmed", "shipped", "delivered", "cancelled"}


def test_order_timestamps_are_consistent(seeded_template: Settings) -> None:
    with connect(seeded_template) as conn:
        shipped = conn.execute(
            "select count(*), count(*) filter (where shipped_at >= ordered_at)"
            " from erp.sales_orders where status in ('shipped', 'delivered')"
        ).fetchone()
        delivered = conn.execute(
            "select count(*), count(*) filter (where delivered_at >= shipped_at)"
            " from erp.sales_orders where status = 'delivered'"
        ).fetchone()
        unshipped = conn.execute(
            "select count(*) from erp.sales_orders"
            " where status in ('placed', 'confirmed', 'cancelled')"
            " and (shipped_at is not null or delivered_at is not null)"
        ).fetchone()
        oldest = conn.execute("select now() - min(ordered_at) from erp.sales_orders").fetchone()
    assert shipped[0] > 0 and shipped[0] == shipped[1]
    assert delivered[0] > 0 and delivered[0] == delivered[1]
    assert unshipped == (0,)
    assert 80 <= oldest[0].days <= 90


def test_customer_names_fit_the_dealer_locale(seeded_template: Settings) -> None:
    with connect(seeded_template) as conn:
        rows = conn.execute(
            "select d.country_code, c.name from erp.customers c"
            " join erp.dealers d on d.id = c.dealer_id"
        ).fetchall()
    non_ascii = {"JP": 0, "ID": 0, "TH": 0}
    totals = {"JP": 0, "ID": 0, "TH": 0}
    for country, name in rows:
        totals[country] += 1
        non_ascii[country] += not name.isascii()
    assert non_ascii["JP"] == totals["JP"]
    assert non_ascii["TH"] == totals["TH"]
    assert non_ascii["ID"] == 0


def test_unit_prices_follow_list_prices(seeded_template: Settings) -> None:
    with connect(seeded_template) as conn:
        rows = conn.execute(
            "select o.currency_code, p.list_price_jpy, l.unit_price from erp.order_lines l"
            " join erp.sales_orders o on o.id = l.order_id join erp.parts p on p.id = l.part_id"
        ).fetchall()
    tolerance = Decimal("0.01")
    for currency, list_price, price in rows:
        full = list_price * FX_PER_JPY[currency]
        assert full * Decimal(str(1 - MAX_DISCOUNT)) - tolerance <= price <= full + tolerance


def test_second_run_changes_nothing(seeded_db: Settings) -> None:
    with connect(seeded_db) as conn:
        before = conn.execute(
            "select max(updated_at), (select max(id) from erp.order_lines) from erp.sales_orders"
        ).fetchone()
    counts = count_rows(seeded_db)
    seed(seeded_db, seed=42)
    assert count_rows(seeded_db) == counts
    with connect(seeded_db) as conn:
        assert (
            conn.execute(
                "select max(updated_at), (select max(id) from erp.order_lines)"
                " from erp.sales_orders"
            ).fetchone()
            == before
        )


def test_same_seed_gives_same_data(base_settings: Settings, migrated_template: Settings) -> None:
    query = (
        "select (select string_agg(dealer_code || name || region, ',' order by id)"
        " from erp.dealers),"
        " (select string_agg(part_number || name || list_price_jpy, ',' order by id)"
        " from erp.parts),"
        " (select string_agg(name || coalesce(email, ''), ',' order by id) from erp.customers),"
        " (select sum(quantity * unit_price) from erp.order_lines)"
    )
    results = []
    for _ in range(2):
        with temp_database(base_settings, template=migrated_template.postgres_db) as settings:
            seed(settings, seed=3)
            with connect(settings) as conn:
                results.append(conn.execute(query).fetchone())
    assert results[0] == results[1]
