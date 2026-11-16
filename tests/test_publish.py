import dataclasses
import threading
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
import pytest

from erp_platform.config import Settings
from erp_platform.pipeline import run
from erp_platform.publish import LAST_SUCCESS_FILE, PUBLISHED_MARTS, publish

ROWS = 300_000


@pytest.fixture
def big_warehouse(pipeline_settings: Settings, tmp_path: Path) -> Settings:
    """A warehouse file whose marts are large enough that writing one takes a while."""
    path = tmp_path / "big.duckdb"
    conn = duckdb.connect(str(path))
    conn.execute("create schema marts")
    for mart in PUBLISHED_MARTS:
        conn.execute(
            f"create table marts.{mart} as "
            f"select i as id, md5(i::varchar) as payload from range({ROWS}) t(i)"
        )
    conn.close()
    return dataclasses.replace(pipeline_settings, warehouse_path=str(path))


def test_reader_never_sees_a_partial_file_while_publishing(big_warehouse: Settings) -> None:
    publish(big_warehouse)
    serving = Path(big_warehouse.serving_dir)
    target = serving / "fct_sales.parquet"
    stop = threading.Event()
    errors: list[str] = []
    reads = 0

    def read_forever() -> None:
        nonlocal reads
        while not stop.is_set():
            try:
                rows = pq.read_table(target).num_rows
            except Exception as exc:  # a truncated file raises; record it for the assertion
                errors.append(repr(exc))
                return
            if rows != ROWS:
                errors.append(f"saw {rows} rows")
                return
            reads += 1

    reader = threading.Thread(target=read_forever)
    reader.start()
    try:
        for _ in range(5):
            publish(big_warehouse)
    finally:
        stop.set()
        reader.join()

    assert errors == []
    assert reads > 0
    assert not list(serving.glob("*.tmp"))


def test_publishing_twice_leaves_the_same_files(pipeline_settings: Settings) -> None:
    run(pipeline_settings)  # ends with publish
    serving = Path(pipeline_settings.serving_dir)

    def snapshot() -> dict[str, int]:
        return {m: pq.read_table(serving / f"{m}.parquet").num_rows for m in PUBLISHED_MARTS}

    first = snapshot()
    names = sorted(p.name for p in serving.iterdir())
    publish(pipeline_settings)

    assert snapshot() == first
    assert sorted(p.name for p in serving.iterdir()) == names
    assert LAST_SUCCESS_FILE in names
    assert first["fct_sales"] > 0
