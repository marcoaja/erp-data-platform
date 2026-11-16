import json
import logging
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pyarrow as pa

from erp_platform.config import Settings
from erp_platform.db import connect
from erp_platform.ingestion.extract import RUN_ID_FORMAT
from erp_platform.storage import Storage, open_storage

log = logging.getLogger(__name__)

PREFIX = "fx_rates"
BASE = "JPY"
QUOTES = ["IDR", "THB"]
# Published rates get revised, so every run re-reads this many days before the last stored one.
REVISION_DAYS = 7
TIMEOUT_SECONDS = 10.0

SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("base", pa.string()),
        ("quote", pa.string()),
        ("rate", pa.decimal128(18, 8)),
        ("_run_id", pa.string()),
        ("_extracted_at", pa.timestamp("us", tz="UTC")),
    ]
)


class FxUnavailable(Exception):
    """The exchange-rate API did not return usable rates."""


def fetch_rates(url: str, start: date, end: date) -> list[dict]:
    """Request daily rates, retrying once; raises FxUnavailable when both attempts fail."""
    params = {
        "base": BASE,
        "quotes": ",".join(QUOTES),
        "from": start.isoformat(),
        "to": end.isoformat(),
    }
    for attempt in (1, 2):
        try:
            response = httpx.get(url, params=params, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            # Rates are parsed as Decimal so no binary float rounding enters the raw layer.
            payload = json.loads(response.text, parse_float=Decimal)
            if not isinstance(payload, list):
                raise ValueError(f"expected a JSON list, got {type(payload).__name__}")
            return payload
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("fx request attempt=%d failed: %s", attempt, exc)
            if attempt == 2:
                raise FxUnavailable(f"exchange-rate API failed: {exc}") from exc
    raise AssertionError("unreachable")


def _last_stored_date(storage: Storage) -> date | None:
    files = [f for f in storage.list_files(PREFIX) if f.endswith(".parquet")]
    if not files:
        return None
    return max(max(storage.read_parquet(f).column("date").to_pylist()) for f in files)


def _first_order_date(settings: Settings) -> date | None:
    with connect(settings, reader=True) as conn:
        row = conn.execute("select min(ordered_at at time zone 'UTC')::date from erp.sales_orders")
        return row.fetchone()[0]  # type: ignore[index]


def fx(settings: Settings) -> int:
    """Fetch JPY-based rates into the raw layer; returns the number of rows written."""
    storage = open_storage(settings)
    last = _last_stored_date(storage)
    if last is None:
        start = _first_order_date(settings)
        if start is None:
            log.info("fx skipped: no orders to price")
            return 0
    else:
        start = last - timedelta(days=REVISION_DAYS)
    now = datetime.now(UTC)
    records = fetch_rates(settings.fx_api_url, start, now.date())
    if not records:
        log.info("fx rows=0 from=%s to=%s", start, now.date())
        return 0

    run_id = now.strftime(RUN_ID_FORMAT)
    path = f"{PREFIX}/extract_date={now:%Y-%m-%d}/{run_id}.parquet"
    if path in storage.list_files(PREFIX):
        # The retry window of a second run is shorter than the first run's, so reusing the name
        # would replace a committed file and lose its dates.
        time.sleep(1.0 - now.microsecond / 1e6 + 0.01)
        now = datetime.now(UTC)
        run_id = now.strftime(RUN_ID_FORMAT)
        path = f"{PREFIX}/extract_date={now:%Y-%m-%d}/{run_id}.parquet"
    rows = [
        (
            date.fromisoformat(r["date"]),
            r["base"],
            r["quote"],
            r["rate"],
            run_id,
            now,
        )
        for r in records
    ]
    table = pa.Table.from_pylist(
        [dict(zip(SCHEMA.names, row, strict=True)) for row in rows], schema=SCHEMA
    )
    storage.write_parquet(path, table)
    log.info("fx rows=%d from=%s to=%s file=%s", table.num_rows, start, now.date(), path)
    return table.num_rows
