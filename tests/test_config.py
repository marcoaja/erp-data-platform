import pytest

from erp_platform.config import load_dashboard_settings, load_settings

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


def test_fx_api_url_defaults_to_frankfurter_and_can_be_overridden() -> None:
    assert load_settings(ENV).fx_api_url == "https://api.frankfurter.dev/v2/rates"
    assert load_settings({**ENV, "FX_API_URL": "http://x/rates"}).fx_api_url == "http://x/rates"


def test_serving_dir_and_schedule_interval_have_defaults() -> None:
    assert load_settings(ENV).serving_dir == "data/serving"
    assert load_settings({**ENV, "SERVING_DIR": "/srv/x"}).serving_dir == "/srv/x"
    dashboard = load_dashboard_settings({})
    assert (dashboard.serving_dir, dashboard.schedule_interval_minutes) == ("data/serving", 30)
    assert (
        load_dashboard_settings({"SCHEDULE_INTERVAL_MINUTES": "5"}).schedule_interval_minutes == 5
    )
