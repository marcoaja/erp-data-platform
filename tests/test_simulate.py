import signal
import threading
from decimal import Decimal

import pytest

from erp_platform.cli import main
from erp_platform.config import Settings
from erp_platform.db import connect
from erp_platform.erp.simulate import FX_PER_JPY, MAX_DISCOUNT, REGIONS, simulate


def test_twenty_ticks_change_the_erp(seeded_db: Settings) -> None:
    with connect(seeded_db) as conn:
        orders_before = dict(conn.execute("select id, status from erp.sales_orders").fetchall())
        prices_before = dict(conn.execute("select id, list_price_jpy from erp.parts").fetchall())
    simulate(seeded_db, ticks=20, seed=7)
    with connect(seeded_db) as conn:
        orders_after = dict(conn.execute("select id, status from erp.sales_orders").fetchall())
        prices_after = dict(conn.execute("select id, list_price_jpy from erp.parts").fetchall())
        # Seeded lines have updated_at = created_at; only a correction moves updated_at later.
        corrected = conn.execute(
            "select count(*) from erp.order_lines l join erp.sales_orders o on o.id = l.order_id"
            " where l.updated_at > l.created_at and o.ordered_at < now() - interval '1 day'"
        ).fetchone()
    assert len(orders_after) > len(orders_before)
    assert any(orders_after[i] != status for i, status in orders_before.items())
    assert any(prices_after[i] != price for i, price in prices_before.items())
    assert corrected[0] >= 1


def test_new_orders_are_priced_from_list_prices(seeded_db: Settings) -> None:
    with connect(seeded_db) as conn:
        max_line = conn.execute("select max(id) from erp.order_lines").fetchone()[0]
        list_prices = dict(conn.execute("select id, list_price_jpy from erp.parts").fetchall())
    # Price changes run after order creation within a tick, so one tick's new lines match the
    # prices read before it.
    simulate(seeded_db, ticks=1, seed=5)
    with connect(seeded_db) as conn:
        rows = conn.execute(
            "select o.currency_code, l.part_id, l.unit_price from erp.order_lines l"
            " join erp.sales_orders o on o.id = l.order_id where l.id > %s",
            (max_line,),
        ).fetchall()
    assert rows
    tolerance = Decimal("0.01")
    for currency, part_id, price in rows:
        full = list_prices[part_id] * FX_PER_JPY[currency]
        assert full * Decimal(str(1 - MAX_DISCOUNT)) - tolerance <= price <= full + tolerance


def test_dealers_only_move_within_their_country(seeded_db: Settings) -> None:
    simulate(seeded_db, ticks=40, seed=2)
    with connect(seeded_db) as conn:
        rows = conn.execute("select country_code, region, updated_at > created_at from erp.dealers")
        dealers = rows.fetchall()
    assert all(region in REGIONS[country] for country, region, _ in dealers)
    assert any(moved for _, _, moved in dealers)


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_interval_mode_stops_cleanly_on_signal(seeded_db: Settings, sig: signal.Signals) -> None:
    with connect(seeded_db) as conn:
        orders_before = conn.execute("select count(*) from erp.sales_orders").fetchone()[0]
    timer = threading.Timer(1.0, signal.raise_signal, [sig])
    timer.start()
    try:
        simulate(seeded_db, interval=0.1, seed=1)
    finally:
        timer.cancel()
    with connect(seeded_db) as conn:
        # The loop ran at least one tick before the signal and returned instead of raising.
        assert conn.execute("select count(*) from erp.sales_orders").fetchone()[0] > orders_before


def test_cli_runs_migrate_seed_simulate(
    empty_db: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POSTGRES_DB", empty_db.postgres_db)
    main(["db", "migrate"])
    main(["seed"])
    main(["simulate", "--ticks", "2", "--seed", "1"])
    with connect(empty_db) as conn:
        statuses = {r[0] for r in conn.execute("select status from erp.sales_orders")}
    assert statuses == {"placed", "confirmed", "shipped", "delivered", "cancelled"}


def test_simulate_requires_ticks_or_interval(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["simulate"])
    assert exc.value.code == 2
