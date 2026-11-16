import dataclasses
from pathlib import Path

import pytest
from helpers import mart_counts, query

from erp_platform.config import Settings
from erp_platform.db import connect
from erp_platform.erp.simulate import simulate
from erp_platform.pipeline import DBT_PROJECT, dbt, run


def test_running_twice_leaves_every_mart_unchanged(pipeline_settings: Settings) -> None:
    run(pipeline_settings)
    first = mart_counts(pipeline_settings)
    # The second extract re-reads the lookback window, so raw now holds duplicate versions.
    run(pipeline_settings)
    assert mart_counts(pipeline_settings) == first
    assert first["fct_sales"] > 0
    assert first["fct_orders"] > 0


def test_price_change_adds_a_version_and_old_orders_keep_the_old_price(
    pipeline_settings: Settings,
) -> None:
    run(pipeline_settings)
    before = query(
        pipeline_settings,
        """select p.part_id, s.list_price_jpy, count(*)
           from marts.fct_sales s join marts.dim_part p using (part_key)
           where p.part_id = 1 group by all""",
    )
    with connect(pipeline_settings) as conn:
        conn.execute("update erp.parts set list_price_jpy = list_price_jpy + 10 where id = 1")
    run(pipeline_settings)

    versions = query(
        pipeline_settings,
        "select list_price_jpy, valid_to is null from marts.dim_part where part_id = 1 "
        "order by valid_from",
    )
    assert len(versions) == len(before) + 1
    assert [is_open for _, is_open in versions] == [False] * (len(versions) - 1) + [True]
    after = query(
        pipeline_settings,
        """select p.part_id, s.list_price_jpy, count(*)
           from marts.fct_sales s join marts.dim_part p using (part_key)
           where p.part_id = 1 group by all""",
    )
    assert sorted(after) == sorted(before)


def test_new_source_column_does_not_break_the_run(pipeline_settings: Settings) -> None:
    run(pipeline_settings)
    first = mart_counts(pipeline_settings)
    with connect(pipeline_settings) as conn:
        conn.execute("alter table erp.parts add column weight_grams integer")
        conn.execute("update erp.parts set weight_grams = 500 where id = 1")
    run(pipeline_settings)
    counts = mart_counts(pipeline_settings)
    assert counts["dim_part"] == first["dim_part"] + 1
    assert counts["fct_sales"] == first["fct_sales"]


def test_failed_extract_stops_before_transform(pipeline_settings: Settings, tmp_path: Path) -> None:
    broken = dataclasses.replace(pipeline_settings, postgres_port=1)
    with pytest.raises(Exception):  # noqa: B017 - any connection error must stop the run
        run(broken)
    assert not Path(pipeline_settings.warehouse_path).exists()


def test_every_analysis_compiles_and_returns_rows(pipeline_settings: Settings) -> None:
    # Stock only runs low once the simulator has shipped orders.
    simulate(pipeline_settings, ticks=50, seed=7)
    run(pipeline_settings)
    assert (
        query(pipeline_settings, "select count(*) from marts.rpt_stockout_risk where is_at_risk")[
            0
        ][0]
        > 0
    )

    dbt(pipeline_settings, "compile")
    compiled = sorted((DBT_PROJECT / "target/compiled/erp_warehouse/analyses").glob("*.sql"))
    assert [f.name for f in compiled] == [
        "q1_stockout_risk.sql",
        "q2_fulfilment_time.sql",
        "q3_sales_by_machine_model.sql",
    ]
    for analysis in compiled:
        assert query(pipeline_settings, analysis.read_text(encoding="utf-8")), analysis.name


def test_every_sale_converts_to_jpy_with_the_published_rate(pipeline_settings: Settings) -> None:
    run(pipeline_settings)
    # Orders on weekends and today have no published rate of their own (the fake API skips
    # weekends), so the check also covers forward filling.
    assert query(
        pipeline_settings, "select count(*) from marts.fct_sales where amount_jpy is null"
    )[0] == (0,)
    jpy_sales = query(
        pipeline_settings,
        "select count(*) from marts.fct_sales where currency_code = 'JPY' "
        "and amount_jpy <> amount_local",
    )
    assert jpy_sales[0] == (0,)
