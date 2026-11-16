import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from erp_platform.config import Settings

log = logging.getLogger(__name__)

REPLACE_RETRY_SECONDS = 5.0

# Whole marts rather than pre-joined reports: the dashboard reuses the joins of the stage 4
# analyses, so the published files stay the star schema the warehouse already tests.
PUBLISHED_MARTS = [
    "rpt_stockout_risk",
    "fct_orders",
    "dim_dealer",
    "fct_sales",
    "dim_part",
    "reconciliation_runs",
]

# Written last, so it exists only for a complete set of files. It is a file, not the files'
# modification times, because the dashboard must know when the last run *succeeded*, and a
# rename-based publish gives every file the time of its own write.
LAST_SUCCESS_FILE = "last_success.json"


def _replace(tmp: Path, target: Path) -> None:
    """Rename `tmp` over `target`, atomically."""
    deadline = time.monotonic() + REPLACE_RETRY_SECONDS
    while True:
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            # Only Windows refuses to replace a file a reader has open (POSIX swaps the name and
            # the reader keeps the old inode). The dashboard's reads are short, so wait them out.
            if time.monotonic() > deadline:
                raise
            time.sleep(0.05)


def publish(settings: Settings) -> None:
    """Export the dashboard's marts to SERVING_DIR; a reader never sees a partial file."""
    serving = Path(settings.serving_dir)
    serving.mkdir(parents=True, exist_ok=True)
    # Read-only, so a publish can run beside a dbt build that is not writing, and never locks
    # out the next one more than DuckDB already does.
    conn = duckdb.connect(settings.warehouse_path, read_only=True)
    try:
        for mart in PUBLISHED_MARTS:
            target = serving / f"{mart}.parquet"
            tmp = serving / f"{mart}.parquet.tmp"
            copied = conn.execute(
                f"copy (select * from marts.{mart}) to '{tmp.as_posix()}' (format parquet)"
            ).fetchone()
            _replace(tmp, target)
            log.info("published %s rows=%s", target, copied[0] if copied else 0)
    finally:
        conn.close()

    marker = serving / LAST_SUCCESS_FILE
    marker_tmp = serving / f"{LAST_SUCCESS_FILE}.tmp"
    marker_tmp.write_text(json.dumps({"finished_at": datetime.now(UTC).isoformat()}))
    _replace(marker_tmp, marker)
    log.info("publish finished dir=%s marts=%d", serving, len(PUBLISHED_MARTS))
