import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg
import pyarrow as pa
from psycopg import sql

from erp_platform.config import Settings
from erp_platform.db import connect
from erp_platform.storage import Storage, open_storage

log = logging.getLogger(__name__)

TABLES = ["dealers", "customers", "parts", "sales_orders", "order_lines"]
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
