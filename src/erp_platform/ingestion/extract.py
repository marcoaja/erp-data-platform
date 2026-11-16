import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg
import pyarrow as pa
from psycopg import sql

from erp_platform.config import Settings
from erp_platform.db import connect
from erp_platform.storage import Storage, open_storage

log = logging.getLogger(__name__)

TABLES = ["dealers", "customers", "parts", "sales_orders", "order_lines", "inventory"]
WATERMARKS = "_state/watermarks.json"
RUN_ID_FORMAT = "%Y%m%dT%H%M%SZ"

_SIMPLE_TYPES: dict[str, pa.DataType] = {
    "int2": pa.int16(),
    "int4": pa.int32(),
    "int8": pa.int64(),
    "text": pa.string(),
    "varchar": pa.string(),
    "bpchar": pa.string(),
    "bool": pa.bool_(),
    "date": pa.date32(),
    "timestamptz": pa.timestamp("us", tz="UTC"),
}


# Metrics beyond the row count, as SQL aggregates. `reconciliation_runs` recomputes the same
# expressions from staging, so a change here needs the same change there.
CONTROL_METRICS: dict[str, dict[str, str]] = {
    "order_lines": {
        "sum_quantity": "sum(quantity)",
        "sum_amount_local": "sum(quantity * unit_price)",
    },
    "inventory": {"sum_quantity_on_hand": "sum(quantity_on_hand)"},
}
CONTROL_TOTALS_TYPE = pa.decimal128(38, 2)


@dataclass(frozen=True)
class Extraction:
    run_id: str
    rows: dict[str, int]


def arrow_type(conn: psycopg.Connection, column: psycopg.Column) -> pa.DataType:
    """Map a cursor column to the Arrow type its declared Postgres type implies."""
    info = conn.adapters.types.get(column.type_code)
    name = info.name if info else f"oid {column.type_code}"
    if name in _SIMPLE_TYPES:
        return _SIMPLE_TYPES[name]
    if name == "numeric" and column.precision is not None and column.scale is not None:
        return pa.decimal128(column.precision, column.scale)
    raise TypeError(f"column {column.name!r} has unmapped Postgres type {name!r}")


def extract(settings: Settings) -> Extraction:
    started = time.monotonic()
    storage = open_storage(settings)
    stored = storage.read_json(WATERMARKS) or {}
    lookback = timedelta(seconds=settings.extract_lookback_seconds)
    rows: dict[str, int] = {}
    previous_run_id = (
        datetime.fromisoformat(max(stored.values())).strftime(RUN_ID_FORMAT) if stored else None
    )

    with connect(settings, reader=True) as conn:
        # One snapshot for every table, so a parent and its children are read at the same instant.
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        conn.read_only = True
        cutoff = conn.execute("select now()").fetchone()[0].astimezone(UTC)
        run_id = cutoff.strftime(RUN_ID_FORMAT)
        if run_id == previous_run_id:
            # A second run inside the same second would overwrite the first run's files, which
            # the watermark has already committed. Wait for the next second and take a new snapshot.
            conn.rollback()
            time.sleep(1.0 - cutoff.microsecond / 1e6 + 0.01)
            cutoff = conn.execute("select now()").fetchone()[0].astimezone(UTC)
            run_id = cutoff.strftime(RUN_ID_FORMAT)
        extracted_at = datetime.now(UTC)
        for table in TABLES:
            watermark = stored.get(table)
            since = datetime.fromisoformat(watermark) - lookback if watermark else None
            rows[table] = _extract_table(conn, storage, table, since, cutoff, run_id, extracted_at)
        for table in TABLES:
            _write_keys(conn, storage, table)
        totals = _control_totals(conn, run_id)
        storage.write_parquet(
            f"control_totals/extract_date={cutoff:%Y-%m-%d}/{run_id}.parquet", totals
        )

    # The state file is the commit point: a crash before this line re-extracts the same window.
    storage.write_json(WATERMARKS, {**stored, **{t: cutoff.isoformat() for t in TABLES}})
    log.info(
        "extract done run_id=%s tables=%d rows=%d duration=%.2fs",
        run_id,
        len(TABLES),
        sum(rows.values()),
        time.monotonic() - started,
    )
    return Extraction(run_id, rows)


def _extract_table(
    conn: psycopg.Connection,
    storage: Storage,
    table: str,
    since: datetime | None,
    cutoff: datetime,
    run_id: str,
    extracted_at: datetime,
) -> int:
    # select * on purpose: a column added to the source flows into raw without a code change.
    query = sql.SQL("select * from erp.{} ").format(sql.Identifier(table))
    params: tuple = ()
    if since is not None:
        query += sql.SQL("where updated_at > %s ")
        params = (since,)
    query += sql.SQL("order by id")
    cur = conn.execute(query, params)
    description = cur.description or []
    records = cur.fetchall()
    if not records:
        log.info("extract table=%s rows=0 file=none", table)
        return 0

    columns = [
        pa.array([r[i] for r in records], type=arrow_type(conn, col))
        for i, col in enumerate(description)
    ]
    names = [col.name for col in description]
    meta = {
        "_run_id": pa.array([run_id] * len(records), type=pa.string()),
        "_extracted_at": pa.array([extracted_at] * len(records), type=pa.timestamp("us", tz="UTC")),
    }
    table_data = pa.table(columns + list(meta.values()), names=names + list(meta))
    path = f"{table}/extract_date={cutoff:%Y-%m-%d}/{run_id}.parquet"
    storage.write_parquet(path, table_data)
    log.info("extract table=%s rows=%d file=%s", table, len(records), path)
    return len(records)


def _control_totals(conn: psycopg.Connection, run_id: str) -> pa.Table:
    """Source totals taken in the extract snapshot, for `reconciliation_runs` to compare against."""
    records: list[tuple[str, str, Decimal]] = []
    for table in TABLES:
        metrics = {"row_count": "count(*)", **CONTROL_METRICS.get(table, {})}
        # Table and expressions are module constants, never input.
        select = ", ".join(f"coalesce({expr}, 0) as {name}" for name, expr in metrics.items())
        row = conn.execute(f"select {select} from erp.{table}").fetchone()
        records += [(table, name, Decimal(value)) for name, value in zip(metrics, row, strict=True)]
    log.info("control totals run_id=%s metrics=%d", run_id, len(records))
    return pa.table(
        {
            "run_id": pa.array([run_id] * len(records), type=pa.string()),
            "table_name": pa.array([r[0] for r in records], type=pa.string()),
            "metric": pa.array([r[1] for r in records], type=pa.string()),
            "value": pa.array([r[2] for r in records], type=CONTROL_TOTALS_TYPE),
        }
    )


def _write_keys(conn: psycopg.Connection, storage: Storage, table: str) -> None:
    """Overwrite the table's live ids: the only way to see a hard delete, which leaves no row."""
    ids = [
        r[0] for r in conn.execute(sql.SQL("select id from erp.{}").format(sql.Identifier(table)))
    ]
    storage.write_parquet(
        f"_keys/{table}/latest.parquet", pa.table({"id": pa.array(ids, pa.int64())})
    )
    log.info("extract table=%s live_keys=%d", table, len(ids))
