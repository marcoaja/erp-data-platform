from pathlib import Path

from helpers import MARTS, query

from erp_platform.config import Settings
from erp_platform.erp.simulate import simulate
from erp_platform.pipeline import run, transform


def fingerprint(settings: Settings) -> dict[str, tuple]:
    """Row count plus a checksum over every column of every row, per mart."""
    return {
        mart: query(settings, f"select count(*), sum(hash(m)::hugeint) from marts.{mart} as m")[0]
        for mart in MARTS
    }


def test_deleting_the_warehouse_and_transforming_rebuilds_every_mart(
    pipeline_settings: Settings,
) -> None:
    run(pipeline_settings)
    # History worth keeping: updates, new versions, deletes, and a second reconciliation run.
    simulate(pipeline_settings, ticks=10, seed=7, with_deletes=True)
    run(pipeline_settings)
    before = fingerprint(pipeline_settings)
    runs_before = query(
        pipeline_settings, "select count(distinct run_id) from marts.reconciliation_runs"
    )
    assert runs_before == [(2,)]
    assert before["fct_sales"][0] > 0 and before["dim_part"][0] > 0

    Path(pipeline_settings.warehouse_path).unlink()
    transform(pipeline_settings)

    assert fingerprint(pipeline_settings) == before
    # The one exception: the history of earlier runs lived only in the warehouse file.
    assert query(
        pipeline_settings, "select count(distinct run_id) from marts.reconciliation_runs"
    ) == [(1,)]
    assert query(
        pipeline_settings, "select count(*) from marts.reconciliation_runs where not is_match"
    ) == [(0,)]
