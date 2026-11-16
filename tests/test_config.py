import pytest

from erp_platform.config import load_settings

ENV = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "erp",
    "POSTGRES_USER": "erp",
    "POSTGRES_PASSWORD": "secret",
}


def test_load_settings_reads_environment() -> None:
    settings = load_settings(ENV)
    assert settings.postgres_port == 5432
    assert settings.postgres_db == "erp"


def test_missing_variable_is_named_in_error() -> None:
    env = {k: v for k, v in ENV.items() if k != "POSTGRES_USER"}
    with pytest.raises(RuntimeError, match="POSTGRES_USER"):
        load_settings(env)


def test_first_missing_variable_is_reported() -> None:
    with pytest.raises(RuntimeError, match="POSTGRES_HOST"):
        load_settings({})
