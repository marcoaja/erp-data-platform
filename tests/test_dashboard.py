import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from erp_platform.config import Settings
from erp_platform.pipeline import run
from erp_platform.publish import LAST_SUCCESS_FILE

APP = str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py")


def render(serving_dir: str, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    # No Postgres or warehouse variables: the dashboard must need only SERVING_DIR.
    for name in ("POSTGRES_HOST", "WAREHOUSE_PATH", "RAW_URI"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SERVING_DIR", serving_dir)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    return at


def test_renders_every_section_from_published_files(
    pipeline_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(pipeline_settings)
    at = render(pipeline_settings.serving_dir, monkeypatch)

    headings = [s.value for s in at.subheader]
    assert [h.split(".")[0] for h in headings] == [
        "Q1",
        "Q2",
        "Q3",
        "Reconciliation history (newest 20 runs)",
    ]
    assert len(at.dataframe) == 3
    charts = at.get("vega_lite_chart")
    assert len(charts) == 1
    spec = json.loads(charts[0].proto.spec)
    categories = spec["encoding"]["y"]  # horizontal: the machine models run down the y axis
    assert categories["sort"] == {"field": "sales_jpy", "order": "descending"}
    assert categories["title"] == "Machine model"
    assert spec["encoding"]["x"]["title"] == "Sales (JPY)"
    assert at.metric[0].label == "Last successful run (UTC)"
    assert not at.warning  # a run that just finished is not stale


def test_warns_when_the_last_run_is_older_than_twice_the_interval(
    pipeline_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(pipeline_settings)
    marker = Path(pipeline_settings.serving_dir) / LAST_SUCCESS_FILE
    marker.write_text('{"finished_at": "2020-01-01T00:00:00+00:00"}')
    at = render(pipeline_settings.serving_dir, monkeypatch)
    assert any("stale" in w.value for w in at.warning)


def test_renders_a_notice_when_nothing_is_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    at = render(str(tmp_path / "empty"), monkeypatch)
    assert [i.value for i in at.info] and not at.subheader
    assert at.warning  # no successful run recorded
