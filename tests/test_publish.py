import dataclasses
import os
import threading
import time
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
import pytest

from erp_platform import publish as publish_module
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
            except PermissionError:
                # Windows refuses to open a file while publish is renaming over it. That is a
                # busy file, not a partial one, so try again.
                time.sleep(0.01)
                continue
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


def test_every_file_is_staged_before_any_rename_and_dimensions_are_renamed_first(
    big_warehouse: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    serving = Path(big_warehouse.serving_dir)
    renamed: list[str] = []
    staged_at_first_rename: list[int] = []
    real_replace = publish_module._replace

    def spy(tmp: Path, target: Path) -> None:
        if not renamed:
            staged_at_first_rename.append(len(list(serving.glob("*.parquet.tmp"))))
        renamed.append(target.name)
        real_replace(tmp, target)

    monkeypatch.setattr(publish_module, "_replace", spy)
    publish(big_warehouse)

    assert staged_at_first_rename == [len(PUBLISHED_MARTS)]
    assert renamed.index("dim_dealer.parquet") < renamed.index("fct_sales.parquet")
    assert renamed.index("dim_part.parquet") < renamed.index("fct_orders.parquet")


def test_a_failed_export_leaves_the_previous_generation_untouched(
    big_warehouse: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    publish(big_warehouse)
    serving = Path(big_warehouse.serving_dir)
    before = {p.name: p.stat().st_mtime_ns for p in serving.glob("*.parquet")}

    monkeypatch.setattr(publish_module, "PUBLISHED_MARTS", [*PUBLISHED_MARTS, "no_such_mart"])
    with pytest.raises(duckdb.Error):
        publish(big_warehouse)

    assert {p.name: p.stat().st_mtime_ns for p in serving.glob("*.parquet")} == before


def test_a_serving_directory_with_an_apostrophe_publishes(
    big_warehouse: Settings, tmp_path: Path
) -> None:
    quoted = dataclasses.replace(big_warehouse, serving_dir=str(tmp_path / "dealer's serving"))
    publish(quoted)
    assert pq.read_table(Path(quoted.serving_dir) / "fct_sales.parquet").num_rows == ROWS


def test_a_blocked_rename_is_retried_and_each_retry_is_logged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tmp, target = tmp_path / "a.tmp", tmp_path / "a"
    tmp.write_text("x")
    real = os.replace
    calls = 0

    def flaky(src: Path, dst: Path) -> None:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise PermissionError(32, "in use")
        real(src, dst)

    monkeypatch.setattr(publish_module.os, "replace", flaky)
    with caplog.at_level("WARNING", logger="erp_platform.publish"):
        publish_module._replace(tmp, target)

    assert target.read_text() == "x"
    assert [r.getMessage() for r in caplog.records] == [
        "replace a is blocked, retry 1",
        "replace a is blocked, retry 2",
    ]
