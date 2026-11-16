import subprocess

import pytest
from helpers import query

from erp_platform.config import Settings
from erp_platform.pipeline import run
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
