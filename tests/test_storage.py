import dataclasses
from pathlib import Path

import pyarrow as pa
import pytest

from erp_platform.config import Settings
from erp_platform.storage import open_storage


@pytest.fixture
def local_settings(base_settings: Settings, tmp_path: Path) -> Settings:
    return dataclasses.replace(base_settings, raw_uri=str(tmp_path / "raw"))


def test_parquet_and_json_round_trip_on_local_disk(local_settings: Settings) -> None:
    storage = open_storage(local_settings)
    table = pa.table({"id": pa.array([1, 2], type=pa.int64()), "name": ["a", None]})

    storage.write_parquet("things/extract_date=2026-01-01/r1.parquet", table)
    storage.write_json("_state/watermarks.json", {"things": "2026-01-01T00:00:00+00:00"})

    assert storage.read_parquet("things/extract_date=2026-01-01/r1.parquet").equals(table)
    assert storage.read_json("_state/watermarks.json") == {"things": "2026-01-01T00:00:00+00:00"}
    assert storage.list_files("things") == ["things/extract_date=2026-01-01/r1.parquet"]
    assert storage.list_files() == [
        "_state/watermarks.json",
        "things/extract_date=2026-01-01/r1.parquet",
    ]


def test_missing_json_is_none_and_missing_prefix_lists_empty(local_settings: Settings) -> None:
    storage = open_storage(local_settings)
    assert storage.read_json("_state/watermarks.json") is None
    assert storage.list_files("nothing") == []


def test_overwriting_json_leaves_no_temporary_file(local_settings: Settings) -> None:
    storage = open_storage(local_settings)
    storage.write_json("_state/a.json", {"v": 1})
    storage.write_json("_state/a.json", {"v": 2})
    assert storage.read_json("_state/a.json") == {"v": 2}
    assert storage.list_files("_state") == ["_state/a.json"]


def test_s3_uri_splits_bucket_and_prefix(local_settings: Settings) -> None:
    settings = dataclasses.replace(
        local_settings,
        raw_uri="s3://bucket/raw/",
        s3_endpoint_url="https://acct.r2.cloudflarestorage.com",
        s3_access_key_id="key",
        s3_secret_access_key="secret",
        s3_region="auto",
    )
    assert open_storage(settings).root == "bucket/raw"
