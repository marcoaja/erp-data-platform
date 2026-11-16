import logging
import os
import subprocess
import sys
from pathlib import Path

from erp_platform.config import Settings
from erp_platform.ingestion.extract import extract
from erp_platform.ingestion.fx import FxUnavailable, fx

log = logging.getLogger(__name__)

DBT_PROJECT = Path(__file__).resolve().parents[2] / "transform"


def dbt(settings: Settings, *args: str) -> None:
    """Run dbt for the configured target; raises when dbt exits non-zero."""
    # Pass the settings explicitly so profiles.yml sees the same values as the rest of the code,
    # not whatever happens to be in the process environment.
    env = {
        **os.environ,
        "RAW_URI": settings.raw_uri,
        "WAREHOUSE_PATH": settings.warehouse_path,
        "DBT_TARGET": settings.dbt_target,
        "PYTHONUTF8": "1",
    }
    command = [
        sys.executable,
        "-m",
        "dbt.cli.main",
        *args,
        "--project-dir",
        str(DBT_PROJECT),
        "--profiles-dir",
        str(DBT_PROJECT),
    ]
    subprocess.run(command, env=env, check=True)


def transform(settings: Settings) -> None:
    if not (DBT_PROJECT / "dbt_packages").exists():
        dbt(settings, "deps")
    dbt(settings, "build")
    log.info(
        "transform finished target=%s warehouse=%s", settings.dbt_target, settings.warehouse_path
    )


def run(settings: Settings) -> None:
    """Run the pipeline steps in order; the first exception stops the run."""
    extract(settings)
    try:
        fx(settings)
    except FxUnavailable as exc:
        # Soft failure: the marts forward-fill from the rates already stored.
        log.warning("fx failed, continuing on the rates already stored: %s", exc)
    transform(settings)
