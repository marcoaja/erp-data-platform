import pytest

from erp_platform.config import load_settings

ENV = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "erp",
    "POSTGRES_USER": "erp",
    "POSTGRES_PASSWORD": "secret",
    "ERP_READER_USER": "erp_reader",
    "ERP_READER_PASSWORD": "reader_secret",
    "RAW_URI": "data/raw",
    "WAREHOUSE_PATH": "data/warehouse.duckdb",
}


def test_load_settings_reads_environment() -> None:
    settings = load_settings(ENV)
    assert settings.postgres_port == 5432
    assert settings.postgres_db == "erp"
    assert settings.erp_reader_user == "erp_reader"


def test_missing_variable_is_named_in_error() -> None:
    env = {k: v for k, v in ENV.items() if k != "POSTGRES_USER"}
    with pytest.raises(RuntimeError, match="POSTGRES_USER"):
        load_settings(env)


def test_first_missing_variable_is_reported() -> None:
    with pytest.raises(RuntimeError, match="POSTGRES_HOST"):
        load_settings({})


def test_optional_settings_default_when_unset() -> None:
    settings = load_settings(ENV)
    assert settings.extract_lookback_seconds == 300
    assert settings.s3_endpoint_url is None


def test_dbt_target_defaults_to_local() -> None:
    assert load_settings(ENV).dbt_target == "local"
    assert load_settings({**ENV, "DBT_TARGET": "snowflake"}).dbt_target == "snowflake"
