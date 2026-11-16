import dataclasses
import logging
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pytest
from fake_frankfurter import FakeFrankfurter, rate_for

from erp_platform.cli import main
from erp_platform.config import Settings
from erp_platform.db import connect
from erp_platform.ingestion.fx import PREFIX, FxUnavailable, fetch_rates, fx
from erp_platform.pipeline import run
from erp_platform.storage import open_storage


@pytest.fixture
def fx_settings(seeded_db: Settings, tmp_path: Path, fx_server: FakeFrankfurter) -> Settings:
    return dataclasses.replace(
        seeded_db,
        raw_uri=str(tmp_path / "raw"),
        warehouse_path=str(tmp_path / "warehouse.duckdb"),
        fx_api_url=fx_server.url,
    )


def stored(settings: Settings) -> pa.Table:
    storage = open_storage(settings)
    files = [f for f in storage.list_files(PREFIX) if f.endswith(".parquet")]
    return pa.concat_tables([storage.read_parquet(f) for f in files])


def first_order_date(settings: Settings) -> date:
    with connect(settings) as conn:
        return conn.execute(
            "select min(ordered_at at time zone 'UTC')::date from erp.sales_orders"
        ).fetchone()[0]


def test_first_run_starts_at_the_earliest_order_and_writes_the_rates(
    fx_settings: Settings, fx_server: FakeFrankfurter
) -> None:
    start = first_order_date(fx_settings)
    written = fx(fx_settings)

    assert fx_server.requests[0]["from"] == start.isoformat()
    assert fx_server.requests[0]["base"] == "JPY"
    assert fx_server.requests[0]["quotes"] == "IDR,THB"
    table = stored(fx_settings)
    assert table.num_rows == written > 0
    assert table.schema.field("rate").type == pa.decimal128(18, 8)
    rows = table.to_pylist()
    assert {r["quote"] for r in rows} == {"IDR", "THB"}
    assert {r["base"] for r in rows} == {"JPY"}
    sample = next(r for r in rows if r["quote"] == "IDR")
    assert sample["rate"] == Decimal(str(rate_for("IDR", sample["date"])))
    assert min(r["date"] for r in rows) >= start


def test_second_run_rereads_seven_days_and_adds_no_new_dates(
    fx_settings: Settings, fx_server: FakeFrankfurter
) -> None:
    fx(fx_settings)
    first = stored(fx_settings)
    last = max(first.column("date").to_pylist())
    fx(fx_settings)

    assert fx_server.requests[1]["from"] == (last - timedelta(days=7)).isoformat()
    second = stored(fx_settings)
    assert set(second.column("date").to_pylist()) == set(first.column("date").to_pylist())
    # Back-to-back runs in one second must still land in separate files.
    assert len({f for f in open_storage(fx_settings).list_files(PREFIX)}) == 2


def test_unreachable_api_is_retried_once_then_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    with pytest.raises(FxUnavailable):
        fetch_rates("http://127.0.0.1:1/v2/rates", date(2026, 1, 1), date(2026, 1, 2))
    assert sum("fx request attempt" in r.message for r in caplog.records) == 2


def test_cli_fx_uses_the_environment(
    fx_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in {
        "POSTGRES_DB": fx_settings.postgres_db,
        "RAW_URI": fx_settings.raw_uri,
        "FX_API_URL": fx_settings.fx_api_url,
    }.items():
        monkeypatch.setenv(name, value)
    main(["fx"])
    assert stored(fx_settings).num_rows > 0


def test_unreachable_api_does_not_stop_erp_run(
    fx_settings: Settings, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(fx_settings)  # stores rates and builds the warehouse
    down = dataclasses.replace(fx_settings, fx_api_url="http://127.0.0.1:1/v2/rates")
    for name, value in {
        "POSTGRES_DB": down.postgres_db,
        "RAW_URI": down.raw_uri,
        "WAREHOUSE_PATH": down.warehouse_path,
        "FX_API_URL": down.fx_api_url,
    }.items():
        monkeypatch.setenv(name, value)
    caplog.set_level(logging.WARNING)

    main(["run"])  # a failing run would raise SystemExit(1)

    assert any(r.levelno == logging.WARNING and "fx failed" in r.message for r in caplog.records)
