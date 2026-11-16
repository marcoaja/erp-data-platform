import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_FX_API_URL = "https://api.frankfurter.dev/v2/rates"
DEFAULT_SERVING_DIR = "data/serving"
DEFAULT_SCHEDULE_INTERVAL_MINUTES = 30


@dataclass(frozen=True)
class Settings:
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    erp_reader_user: str
    erp_reader_password: str
    raw_uri: str
    extract_lookback_seconds: int
    warehouse_path: str
    serving_dir: str
    dbt_target: str
    fx_api_url: str
    s3_endpoint_url: str | None
    s3_access_key_id: str | None
    s3_secret_access_key: str | None
    s3_region: str | None


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read settings from `env`, defaulting to the process environment."""
    env = os.environ if env is None else env

    def require(name: str) -> str:
        value = env.get(name)
        if not value:
            raise RuntimeError(f"Missing required environment variable: {name}")
        return value

    return Settings(
        postgres_host=require("POSTGRES_HOST"),
        postgres_port=int(require("POSTGRES_PORT")),
        postgres_db=require("POSTGRES_DB"),
        postgres_user=require("POSTGRES_USER"),
        postgres_password=require("POSTGRES_PASSWORD"),
        erp_reader_user=require("ERP_READER_USER"),
        erp_reader_password=require("ERP_READER_PASSWORD"),
        raw_uri=require("RAW_URI"),
        extract_lookback_seconds=int(env.get("EXTRACT_LOOKBACK_SECONDS") or 300),
        warehouse_path=require("WAREHOUSE_PATH"),
        serving_dir=env.get("SERVING_DIR") or DEFAULT_SERVING_DIR,
        dbt_target=env.get("DBT_TARGET") or "local",
        fx_api_url=env.get("FX_API_URL") or DEFAULT_FX_API_URL,
        s3_endpoint_url=env.get("S3_ENDPOINT_URL") or None,
        s3_access_key_id=env.get("S3_ACCESS_KEY_ID") or None,
        s3_secret_access_key=env.get("S3_SECRET_ACCESS_KEY") or None,
        s3_region=env.get("S3_REGION") or None,
    )


@dataclass(frozen=True)
class DashboardSettings:
    serving_dir: str
    schedule_interval_minutes: int


def load_dashboard_settings(env: Mapping[str, str] | None = None) -> DashboardSettings:
    """The dashboard's subset of the settings; it must start without Postgres or the warehouse."""
    env = os.environ if env is None else env
    return DashboardSettings(
        serving_dir=env.get("SERVING_DIR") or DEFAULT_SERVING_DIR,
        schedule_interval_minutes=int(
            env.get("SCHEDULE_INTERVAL_MINUTES") or DEFAULT_SCHEDULE_INTERVAL_MINUTES
        ),
    )
