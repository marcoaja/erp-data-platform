import dataclasses
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pytest

from erp_platform.cli import main
from erp_platform.config import Settings
from erp_platform.db import connect
from erp_platform.ingestion.extract import TABLES, WATERMARKS, extract
from erp_platform.storage import Storage, open_storage


@pytest.fixture
def source(seeded_db: Settings, tmp_path: Path) -> Settings:
    """Seeded ERP copy with a private, empty raw layer."""
    return dataclasses.replace(seeded_db, raw_uri=str(tmp_path / "raw"))


def raw_files(storage: Storage, table: str) -> list[str]:
    return [f for f in storage.list_files(table) if f.endswith(".parquet")]


def raw_rows(storage: Storage, table: str) -> pa.Table:
    return pa.concat_tables([storage.read_parquet(f) for f in raw_files(storage, table)])


def version_pairs(storage: Storage) -> set[tuple[str, int, datetime]]:
    return {
        (table, row["id"], row["updated_at"])
        for table in TABLES
        for row in raw_rows(storage, table).select(["id", "updated_at"]).to_pylist()
    }


def source_count(settings: Settings, table: str) -> int:
    with connect(settings) as conn:
        return conn.execute(f"select count(*) from erp.{table}").fetchone()[0]


def test_first_extract_writes_one_file_per_table_with_every_row(source: Settings) -> None:
    result = extract(source)
    storage = open_storage(source)
    for table in TABLES:
        files = raw_files(storage, table)
        assert len(files) == 1
        assert files[0].endswith(f"/{result.run_id}.parquet")
        rows = storage.read_parquet(files[0])
        assert rows.num_rows == source_count(source, table)
        assert set(rows["_run_id"].to_pylist()) == {result.run_id}
    marks = storage.read_json(WATERMARKS)
    assert set(marks) == set(TABLES)
    assert len(set(marks.values())) == 1


def test_all_null_column_keeps_its_declared_type(source: Settings) -> None:
    with connect(source) as conn:
        conn.execute("update erp.customers set phone = null")
    extract(source)
    storage = open_storage(source)
    customers = raw_rows(storage, "customers")
    assert customers.column("phone").null_count == customers.num_rows
    assert customers.schema.field("phone").type == pa.string()
    parts = raw_rows(storage, "parts").schema
    assert parts.field("list_price_jpy").type == pa.decimal128(12, 2)
    assert parts.field("updated_at").type == pa.timestamp("us", tz="UTC")
    assert parts.field("is_active").type == pa.bool_()
    assert parts.field("id").type == pa.int64()


def test_unmapped_type_names_the_column(source: Settings) -> None:
    with connect(source) as conn:
        conn.execute("alter table erp.parts add column lead_time interval")
    with pytest.raises(TypeError, match="lead_time"):
        extract(source)
    assert open_storage(source).read_json(WATERMARKS) is None


def test_new_source_column_flows_into_raw_and_old_files_stay_readable(source: Settings) -> None:
    extract(source)
    with connect(source) as conn:
        conn.execute("alter table erp.parts add column origin text")
        conn.execute(
            "update erp.parts set origin = 'JP' where id = (select min(id) from erp.parts)"
        )
    extract(source)
    storage = open_storage(source)
    files = raw_files(storage, "parts")
    assert len(files) == 2
    assert "origin" not in storage.read_parquet(files[0]).column_names
    assert storage.read_parquet(files[1]).column("origin").to_pylist() == ["JP"]


def test_second_extract_without_changes_adds_nothing(source: Settings) -> None:
    extract(source)
    storage = open_storage(source)
    first = version_pairs(storage)
    extract(source)
    assert version_pairs(storage) == first
    # Master data is older than the lookback window, so nothing re-reads it. Orders created
    # inside the window are re-read, which at-least-once delivery allows.
    assert len(raw_files(storage, "dealers")) == 1


def test_second_extract_holds_the_changes_and_only_the_lookback_window(source: Settings) -> None:
    extract(source)
    storage = open_storage(source)
    watermark = datetime.fromisoformat(storage.read_json(WATERMARKS)["parts"])
    with connect(source) as conn:
        ids = [r[0] for r in conn.execute("select id from erp.parts order by id limit 3")]
        conn.execute("update erp.parts set name = name || '!' where id = any(%s)", (ids,))
        conn.execute(
            "insert into erp.parts (part_number, name, machine_model, category, list_price_jpy)"
            " select 'NEW-' || g, 'New part', 'M1', 'Filters', 100 from generate_series(1, 2) g"
        )
        window_start = watermark - timedelta(seconds=source.extract_lookback_seconds)
        expected = {
            r[0]
            for r in conn.execute("select id from erp.parts where updated_at > %s", (window_start,))
        }
    extract(source)
    files = raw_files(storage, "parts")
    assert len(files) == 2
    second_ids = set(storage.read_parquet(files[1])["id"].to_pylist())
    assert second_ids == expected
    assert len(second_ids) == 5  # seeded rows are historical, so only the five changes qualify
    assert set(ids) <= second_ids
    assert len(raw_files(storage, "dealers")) == 1


def test_lookback_catches_a_row_committed_after_the_cutoff(source: Settings) -> None:
    extract(source)
    storage = open_storage(source)
    writer = connect(source)
    try:
        writer.execute(
            "update erp.parts set name = 'late' where id = (select min(id) from erp.parts)"
        )
        extract(source)  # the update is uncommitted, so this run cannot see it
        assert "late" not in raw_rows(storage, "parts")["name"].to_pylist()
        writer.commit()
    finally:
        writer.close()
    extract(source)
    assert "late" in raw_rows(storage, "parts")["name"].to_pylist()


def test_failed_state_write_keeps_the_watermark_and_the_retry_loses_nothing(
    source: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    extract(source)
    storage = open_storage(source)
    before = storage.read_json(WATERMARKS)
    with connect(source) as conn:
        conn.execute("update erp.parts set name = 'changed' where id <= 3")

    def fail(self: Storage, relative: str, value: object) -> None:
        raise OSError("state write failed")

    with monkeypatch.context() as patch:
        patch.setattr(Storage, "write_json", fail)
        with pytest.raises(OSError, match="state write failed"):
            extract(source)
    assert storage.read_json(WATERMARKS) == before

    extract(source)
    changed = [r for r in raw_rows(storage, "parts").to_pylist() if r["name"] == "changed"]
    assert {r["id"] for r in changed} == {1, 2, 3}
    assert storage.read_json(WATERMARKS) != before


def test_back_to_back_runs_never_overwrite_a_committed_file(source: Settings) -> None:
    first = extract(source)
    with connect(source) as conn:
        conn.execute("update erp.parts set name = 'x' where id = 1")
    second = extract(source)
    assert second.run_id != first.run_id
    assert len(raw_files(open_storage(source), "parts")) == 2


def test_log_names_every_table_and_the_run(
    source: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="erp_platform.ingestion.extract"):
        result = extract(source)
    text = "\n".join(caplog.messages)
    orders = source_count(source, "sales_orders")
    assert f"table=sales_orders rows={orders} file=sales_orders/" in text
    assert f"extract done run_id={result.run_id}" in text and "duration=" in text


def test_cli_extract_uses_the_environment(
    source: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POSTGRES_DB", source.postgres_db)
    monkeypatch.setenv("RAW_URI", source.raw_uri)
    main(["extract"])
    assert raw_rows(open_storage(source), "dealers").num_rows == source_count(source, "dealers")


def test_decimal_values_survive_exactly(source: Settings) -> None:
    extract(source)
    with connect(source) as conn:
        price = conn.execute("select list_price_jpy from erp.parts where id = 1").fetchone()[0]
    raw = raw_rows(open_storage(source), "parts").to_pylist()
    assert isinstance(price, Decimal)
    assert next(r for r in raw if r["id"] == 1)["list_price_jpy"] == price
