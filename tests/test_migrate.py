from pathlib import Path

import psycopg
import pytest

from erp_platform.config import Settings
from erp_platform.db import connect
from erp_platform.erp.migrate import apply_migrations, migrate

# One statement per table that changes a column without touching updated_at.
TOUCH = {
    "dealers": "update erp.dealers set name = name || '!'",
    "customers": "update erp.customers set name = name || '!'",
    "parts": "update erp.parts set name = name || '!'",
    "sales_orders": "update erp.sales_orders set status = 'confirmed'",
    "order_lines": "update erp.order_lines set quantity = quantity + 1",
    "inventory": "update erp.inventory set quantity_on_hand = quantity_on_hand + 1",
}


def test_second_migrate_applies_nothing(empty_db: Settings) -> None:
    migrate(empty_db)
    migrate(empty_db)  # the reader role already exists on the second run
    with connect(empty_db, autocommit=True) as conn:
        assert apply_migrations(conn) == []
        filenames = [r[0] for r in conn.execute("select filename from erp.schema_migrations")]
    assert filenames == ["001_initial.sql", "002_inventory.sql"]


def test_failing_migration_leaves_no_partial_change(empty_db: Settings, tmp_path: Path) -> None:
    (tmp_path / "001_bad.sql").write_text("create table erp.partial (id int); select 1 / 0;")
    with connect(empty_db, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.DivisionByZero):
            apply_migrations(conn, tmp_path)
        assert conn.execute("select to_regclass('erp.partial')").fetchone() == (None,)
        assert conn.execute("select count(*) from erp.schema_migrations").fetchone() == (0,)


def test_updated_at_advances_without_being_set(migrated_db: Settings) -> None:
    with connect(migrated_db, autocommit=True) as conn:
        conn.execute(
            "insert into erp.dealers (dealer_code, name, country_code, region, currency_code)"
            " values ('JP-001', 'Dealer', 'JP', 'Kanto', 'JPY')"
        )
        conn.execute("insert into erp.customers (dealer_id, name) values (1, 'Customer')")
        conn.execute(
            "insert into erp.parts (part_number, name, machine_model, category, list_price_jpy)"
            " values ('P-1', 'Part', 'T-250', 'Engine', 1000)"
        )
        conn.execute(
            "insert into erp.sales_orders (dealer_id, customer_id, status, currency_code)"
            " values (1, 1, 'placed', 'JPY')"
        )
        conn.execute(
            "insert into erp.order_lines (order_id, line_number, part_id, quantity, unit_price)"
            " values (1, 1, 1, 2, 900)"
        )
        conn.execute(
            "insert into erp.inventory (dealer_id, part_id, quantity_on_hand, reorder_point)"
            " values (1, 1, 10, 5)"
        )
        for table, update in TOUCH.items():
            before = conn.execute(f"select updated_at from erp.{table}").fetchone()
            conn.execute(update)
            after = conn.execute(f"select updated_at from erp.{table}").fetchone()
            assert before is not None and after is not None
            assert after[0] > before[0], table


def test_reader_can_select_but_not_insert(migrated_db: Settings) -> None:
    with connect(migrated_db, reader=True, autocommit=True) as conn:
        assert conn.execute("select count(*) from erp.dealers").fetchone() == (0,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "insert into erp.dealers (dealer_code, name, country_code, region, currency_code)"
                " values ('JP-001', 'Dealer', 'JP', 'Kanto', 'JPY')"
            )


def test_reader_sees_tables_added_by_later_migrations(
    migrated_db: Settings, tmp_path: Path
) -> None:
    (tmp_path / "002_extra.sql").write_text("create table erp.extra (id int);")
    with connect(migrated_db, autocommit=True) as owner:
        assert apply_migrations(owner, tmp_path) == ["002_extra.sql"]
    with connect(migrated_db, reader=True, autocommit=True) as reader:
        assert reader.execute("select count(*) from erp.extra").fetchone() == (0,)
