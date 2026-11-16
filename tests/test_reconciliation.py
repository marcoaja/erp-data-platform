import subprocess

import duckdb
import pyarrow.compute as pc
import pytest
from helpers import query

from erp_platform.config import Settings
from erp_platform.db import connect
from erp_platform.ingestion.extract import extract
from erp_platform.ingestion.fx import fx
from erp_platform.pipeline import run, transform
from erp_platform.storage import open_storage


def test_every_total_matches_after_a_run_and_history_accumulates(
    pipeline_settings: Settings,
) -> None:
    run(pipeline_settings)
    rows = query(pipeline_settings, "select run_id, is_match from marts.reconciliation_runs")
    assert len(rows) == 9  # six row counts, two sums on order_lines, one on inventory
    assert all(is_match for _, is_match in rows)

    run(pipeline_settings)
    runs = {
        r for r, _ in query(pipeline_settings, "select run_id, 1 from marts.reconciliation_runs")
    }
    assert len(runs) == 2
    assert query(pipeline_settings, "select count(*) from marts.reconciliation_runs") == [(18,)]
    assert query(
        pipeline_settings, "select count(*) from marts.reconciliation_runs where not is_match"
    ) == [(0,)]


def test_an_edited_raw_value_fails_the_run_and_names_the_table_and_metric(
    pipeline_settings: Settings, capfd: pytest.CaptureFixture[str]
) -> None:
    run(pipeline_settings)
    storage = open_storage(pipeline_settings)
    (path,) = [f for f in storage.list_files("order_lines") if f.endswith(".parquet")]
    lines = storage.read_parquet(path)
    quantities = lines["quantity"].to_pylist()
    quantities[0] += 1  # one unit more than the ERP holds
    storage.write_parquet(
        path, lines.set_column(lines.schema.get_field_index("quantity"), "quantity", [quantities])
    )

    with pytest.raises(subprocess.CalledProcessError):
        run(pipeline_settings)

    output = capfd.readouterr().out
    assert "order_lines" in output.split("reconciliation_matches_source")[-1]
    assert "sum_quantity" in output


def test_a_later_run_id_in_the_history_cannot_hide_a_mismatch_in_the_current_run(
    pipeline_settings: Settings,
) -> None:
    run(pipeline_settings)
    warehouse = duckdb.connect(pipeline_settings.warehouse_path)
    try:
        # A matching row from a run id that sorts after every real one, as a clock step back would
        # leave in the history.
        warehouse.execute(
            "insert into marts.reconciliation_runs"
            " select '99991231T235959Z', table_name, metric, source_value, warehouse_value, 0, true"
            " from marts.reconciliation_runs"
        )
    finally:
        warehouse.close()
    storage = open_storage(pipeline_settings)
    (path,) = [f for f in storage.list_files("order_lines") if f.endswith(".parquet")]
    lines = storage.read_parquet(path)
    quantities = lines["quantity"].to_pylist()
    quantities[0] += 1
    storage.write_parquet(
        path, lines.set_column(lines.schema.get_field_index("quantity"), "quantity", [quantities])
    )

    with pytest.raises(subprocess.CalledProcessError):
        run(pipeline_settings)


def test_hard_deleted_lines_leave_the_facts_and_the_totals_still_match(
    pipeline_settings: Settings,
) -> None:
    run(pipeline_settings)
    with connect(pipeline_settings) as conn:
        deleted = [
            r[0]
            for r in conn.execute(
                "delete from erp.order_lines where id in (select id from erp.order_lines"
                " order by id desc limit 3) returning id"
            )
        ]
    run(pipeline_settings)

    ids = ", ".join(str(i) for i in deleted)
    assert query(
        pipeline_settings,
        f"select count(*) from staging.stg_erp__order_lines where is_deleted and is_current"
        f" and order_line_id in ({ids})",
    ) == [(3,)]
    assert query(
        pipeline_settings, f"select count(*) from marts.fct_sales where order_line_id in ({ids})"
    ) == [(0,)]
    assert query(
        pipeline_settings, "select count(*) from marts.reconciliation_runs where not is_match"
    ) == [(0,)]


def test_a_newest_run_missing_expected_metrics_fails(pipeline_settings: Settings) -> None:
    extract(pipeline_settings)
    fx(pipeline_settings)
    storage = open_storage(pipeline_settings)
    (path,) = [f for f in storage.list_files("control_totals") if f.endswith(".parquet")]
    totals = storage.read_parquet(path)
    assert totals.num_rows == 9
    # Keep six of the nine metrics, as a partial or older extract would.
    kept = totals.filter(~pc.field("table_name").isin(["dealers", "customers", "parts"]))
    assert kept.num_rows == 6
    storage.write_parquet(path, kept)

    with pytest.raises(subprocess.CalledProcessError):
        transform(pipeline_settings)
