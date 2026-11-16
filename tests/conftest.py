import dataclasses
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fake_frankfurter import FakeFrankfurter
from psycopg import sql

from erp_platform.config import Settings, load_settings
from erp_platform.db import connect
from erp_platform.erp.migrate import migrate
from erp_platform.erp.seed import seed


@contextmanager
def temp_database(base: Settings, template: str | None = None) -> Iterator[Settings]:
    """Create a throwaway database next to the configured one and drop it afterwards."""
    name = f"erp_test_{uuid.uuid4().hex[:12]}"
    create = sql.SQL("create database {}").format(sql.Identifier(name))
    if template:
        create += sql.SQL(" template {}").format(sql.Identifier(template))
    with connect(base, autocommit=True) as admin:
        admin.execute(create)
    try:
        yield dataclasses.replace(base, postgres_db=name)
    finally:
        with connect(base, autocommit=True) as admin:
            admin.execute(
                sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(name))
            )


@pytest.fixture(scope="session")
def base_settings() -> Settings:
    return load_settings()


@pytest.fixture(scope="session")
def migrated_template(base_settings: Settings) -> Iterator[Settings]:
    with temp_database(base_settings) as settings:
        migrate(settings)
        yield settings


@pytest.fixture
def empty_db(base_settings: Settings) -> Iterator[Settings]:
    with temp_database(base_settings) as settings:
        yield settings


@pytest.fixture
def migrated_db(base_settings: Settings, migrated_template: Settings) -> Iterator[Settings]:
    with temp_database(base_settings, template=migrated_template.postgres_db) as settings:
        yield settings


@pytest.fixture(scope="session")
def seeded_template(base_settings: Settings, migrated_template: Settings) -> Iterator[Settings]:
    with temp_database(base_settings, template=migrated_template.postgres_db) as settings:
        seed(settings, seed=42)
        yield settings


@pytest.fixture
def seeded_db(base_settings: Settings, seeded_template: Settings) -> Iterator[Settings]:
    """A private copy of the seeded database that a test may change."""
    with temp_database(base_settings, template=seeded_template.postgres_db) as settings:
        yield settings


@pytest.fixture
def fx_server() -> Iterator[FakeFrankfurter]:
    server = FakeFrankfurter()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def pipeline_settings(seeded_db: Settings, tmp_path: Path, fx_server: FakeFrankfurter) -> Settings:
    """Seeded ERP copy with a private raw layer and warehouse file."""
    return dataclasses.replace(
        seeded_db,
        raw_uri=str(tmp_path / "raw"),
        warehouse_path=str(tmp_path / "warehouse.duckdb"),
        fx_api_url=fx_server.url,
    )
