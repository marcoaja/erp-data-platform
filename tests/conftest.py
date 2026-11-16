import dataclasses
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from psycopg import sql

from erp_platform.config import Settings, load_settings
from erp_platform.db import connect
from erp_platform.erp.migrate import migrate


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
