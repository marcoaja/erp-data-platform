import dataclasses
import logging
from pathlib import Path

import pytest
from fake_frankfurter import FakeFrankfurter
from helpers import query

from erp_platform.config import Settings
from erp_platform.db import connect
from erp_platform.erp.migrate import apply_migrations
from erp_platform.ingestion.extract import SCHEMAS, WATERMARKS, SourceSchemaChanged, extract
from erp_platform.ingestion.fx import fx
from erp_platform.pipeline import transform
from erp_platform.storage import open_storage


def add_column_migration(
    tmp_path: Path, table: str = "sales_orders", column: str = "sales_channel text"
) -> Path:
    directory = tmp_path / "migrations"
    directory.mkdir(exist_ok=True)
    (directory / "900_add_column.sql").write_text(f"alter table erp.{table} add column {column};")
    return directory


def test_old_and_new_raw_files_read_together_after_a_column_is_added(
    pipeline_settings: Settings, tmp_path: Path
) -> None:
    with connect(pipeline_settings, autocommit=True) as conn:
        # Start from a source that predates the column, then add it back the way a deployment would.
        conn.execute("alter table erp.sales_orders drop column sales_channel")
    extract(pipeline_settings)
    with connect(pipeline_settings, autocommit=True) as conn:
        assert apply_migrations(conn, add_column_migration(tmp_path)) == ["900_add_column.sql"]
        conn.execute(
            "update erp.sales_orders set sales_channel = 'phone'"
            " where id = (select min(id) from erp.sales_orders)"
        )
    extract(pipeline_settings)
    fx(pipeline_settings)

    # Without union_by_name in the source definition, the first file's columns would win and the
    # new column would be missing from the read, so dbt would fail here.
    transform(pipeline_settings)

    assert (
        query(
            pipeline_settings,
            "select count(*), count(sales_channel) from marts.fct_orders",
        )[0][1]
        == 1
    )
    assert query(
        pipeline_settings,
        "select sales_channel from marts.fct_orders where sales_channel is not null",
    ) == [("phone",)]


def raw_listing(settings: Settings) -> list[str]:
    return open_storage(settings).list_files()


def test_added_column_is_logged_accepted_and_backfills_a_quiet_table(
    source: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    extract(source)
    storage = open_storage(source)
    with connect(source, autocommit=True) as conn:
        apply_migrations(conn, add_column_migration(tmp_path, "customers", "loyalty_tier text"))
    with caplog.at_level(logging.WARNING, logger="erp_platform.ingestion.extract"):
        extract(source)  # no customer changed, yet the new column must reach raw

    assert "table=customers added columns=loyalty_tier" in caplog.text
    files = [f for f in storage.list_files("customers") if f.endswith(".parquet")]
    assert len(files) == 2
    assert "loyalty_tier" in storage.read_parquet(files[1]).column_names
    assert "loyalty_tier" in storage.read_json(SCHEMAS)["customers"]
    extract(source)  # accepted: the third run is quiet
    assert len([f for f in storage.list_files("customers") if f.endswith(".parquet")]) == 2


def test_dropped_column_stops_the_run_before_anything_is_written(source: Settings) -> None:
    extract(source)
    storage = open_storage(source)
    watermarks, schemas, listing = (
        storage.read_json(WATERMARKS),
        storage.read_json(SCHEMAS),
        raw_listing(source),
    )
    with connect(source, autocommit=True) as conn:
        conn.execute("alter table erp.customers drop column phone")
        conn.execute("update erp.parts set name = 'changed' where id = 1")

    with pytest.raises(SourceSchemaChanged, match=r"customers\.phone was removed"):
        extract(source)

    assert storage.read_json(WATERMARKS) == watermarks
    assert storage.read_json(SCHEMAS) == schemas
    assert raw_listing(source) == listing


def test_retyped_column_stops_the_run_and_names_both_types(source: Settings) -> None:
    extract(source)
    with connect(source, autocommit=True) as conn:
        conn.execute("alter table erp.parts alter column list_price_jpy type numeric(14, 2)")
    with pytest.raises(SourceSchemaChanged, match=r"parts\.list_price_jpy.*decimal128\(12, 2\).*"):
        extract(source)


def test_documented_accept_procedure_lets_the_run_continue(
    source: Settings, fx_server: FakeFrankfurter
) -> None:
    source = dataclasses.replace(source, fx_api_url=fx_server.url)
    extract(source)
    with connect(source, autocommit=True) as conn:
        conn.execute("alter table erp.customers drop column phone")
        conn.execute("update erp.customers set city = 'Moved' where id = 1")
    with pytest.raises(SourceSchemaChanged):
        extract(source)

    # The procedure in docs/incidents/schema-evolution.md: remove the table's stored schema.
    storage = open_storage(source)
    schemas = storage.read_json(SCHEMAS)
    del schemas["customers"]
    storage.write_json(SCHEMAS, schemas)

    extract(source)
    assert "phone" not in storage.read_json(SCHEMAS)["customers"]
    fx(source)
    transform(source)
    # Old files still hold phone numbers; the changed row's new version has none.
    assert query(
        source, "select count(*) from marts.dim_customer where city = 'Moved' and phone is null"
    ) == [(1,)]
