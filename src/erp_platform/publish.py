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
# Dimensions first: publish renames the files in this order (see `publish`).
PUBLISHED_MARTS = [
    "dim_dealer",
    "dim_part",
    "fct_orders",
    "fct_sales",
    "rpt_stockout_risk",
    "reconciliation_runs",
]

# Written by `erp run` after publish and reconciliation have both succeeded, so it exists only for
# a complete, verified set of files. It is a file, not the files' modification times, because the
# dashboard must know when the last run *succeeded*, and a rename-based publish gives every file
# the time of its own write.
LAST_SUCCESS_FILE = "last_success.json"


def _sql_literal(path: Path) -> str:
    """A path as a single-quoted SQL string; an apostrophe in a directory name must not end it."""
    return "'" + path.as_posix().replace("'", "''") + "'"


def _replace(tmp: Path, target: Path) -> None:
    """Rename `tmp` over `target`, atomically."""
    deadline = time.monotonic() + REPLACE_RETRY_SECONDS
    attempt = 0
    while True:
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            # Only Windows refuses to replace a file a reader has open (POSIX swaps the name and
            # the reader keeps the old inode). The dashboard's reads are short, so wait them out.
            if time.monotonic() > deadline:
                raise
            attempt += 1
            log.warning("replace %s is blocked, retry %d", target.name, attempt)
            time.sleep(0.05)


def publish(settings: Settings) -> None:
    """Export the dashboard's marts to SERVING_DIR; a reader never sees a partial file."""
    serving = Path(settings.serving_dir)
    serving.mkdir(parents=True, exist_ok=True)
    # Read-only, because DuckDB lets one writing process hold the file: a publish started while a
    # dbt build is writing fails to open it, and the failure propagates.
    conn = duckdb.connect(settings.warehouse_path, read_only=True)
    staged: list[tuple[Path, Path]] = []
    try:
        # Write every temporary file first, so a failure while exporting leaves the previous
        # generation untouched.
        for mart in PUBLISHED_MARTS:
            target = serving / f"{mart}.parquet"
            tmp = serving / f"{mart}.parquet.tmp"
            copied = conn.execute(
                f"copy (select * from marts.{mart}) to {_sql_literal(tmp)} (format parquet)"
            ).fetchone()
            staged.append((tmp, target))
            log.info("exported %s rows=%s", tmp.name, copied[0] if copied else 0)
    finally:
        conn.close()

    # Dimensions come first in PUBLISHED_MARTS. Surrogate keys hash (id, valid_from), so the new
    # dimensions still contain every key the old facts use: a reader that sees new dimensions and
    # old facts can join them, the reverse order could not.
    for tmp, target in staged:
        _replace(tmp, target)
        log.info("published %s", target)
    log.info("publish finished dir=%s marts=%d", serving, len(PUBLISHED_MARTS))


def write_last_success(settings: Settings) -> None:
    """Record now as the last successful run, replacing the marker atomically."""
    serving = Path(settings.serving_dir)
    marker = serving / LAST_SUCCESS_FILE
    marker_tmp = serving / f"{LAST_SUCCESS_FILE}.tmp"
    marker_tmp.write_text(json.dumps({"finished_at": datetime.now(UTC).isoformat()}))
    _replace(marker_tmp, marker)
    log.info("last success recorded at %s", marker)
