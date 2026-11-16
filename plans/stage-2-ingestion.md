# Stage 2: Incremental ingestion

**Goal.** `erp extract` copies every new and changed ERP row into the raw layer, and running it again never loses or corrupts data.

**Depends on.** Stage 1.

**Human prerequisites.** None. This stage runs against a local `RAW_URI`; the storage code already accepts `s3://` URIs so stage 6 only changes configuration.

The file layout, the extract protocol, and its guarantees are specified under "Raw layer" in [ARCHITECTURE.md](ARCHITECTURE.md). Implement that protocol exactly; the tests below are how you prove it.

## Tasks

- [x] **Write `storage.py`.** One function that turns `RAW_URI` and the `S3_*` settings into a `pyarrow.fs` filesystem and a root path, plus helpers to write a Parquet table, read and write a small JSON object, and list files. Add `pyarrow` as a dependency.
  Done when: a pytest round-trips Parquet and JSON through a temporary local directory.
- [x] **Map Postgres types to Arrow types** from the cursor's column metadata: integers, `numeric(p,s)` to `decimal128(p,s)`, `text`, `boolean`, `date`, `timestamptz` to `timestamp('us', tz='UTC')`. An unmapped type raises an error naming the column.
  Done when: a pytest extracts a table whose nullable column is entirely null and the written file still has that column's declared type.
- [x] **Write `erp extract`.** Follow the five protocol steps. Connect as the reader role. Tables are listed once, in a module constant. A table with no changed rows writes no file.
  Done when: after `erp seed`, one extract writes one file per table whose row count equals the table's.
- [x] **Prove idempotency.** 
  Done when: a pytest runs extract twice with no source change and the distinct (`id`, `updated_at`) pairs across all raw files equal those after the first run.
- [x] **Prove incremental capture.**
  Done when: a pytest updates three rows and inserts two between extracts, and the second run's file holds those five rows plus only rows inside the lookback window.
- [x] **Prove the lookback catches a late commit.**
  Done when: a pytest opens a transaction, updates a row, runs an extract, commits, runs a second extract, and finds the update in raw.
- [x] **Prove the commit point.**
  Done when: a pytest makes the state write fail, sees the watermark unchanged, runs extract again, and finds every changed row in raw.
- [x] **Log the run.** One line per table with the row count and file path, and one summary line with the `run_id` and duration.
  Done when: the log of one run is enough to tell what was extracted without opening a file.
- [x] **Extend CI** with the new tests.
  Done when: the CI commands pass locally.

## Acceptance

```bash
uv run --env-file .env erp extract
uv run --env-file .env erp simulate --ticks 10 --seed 7
uv run --env-file .env erp extract
uv run --env-file .env pytest
uv run ruff check . && uv run ruff format --check .
```

After these commands, `data/raw/` holds two `run_id` files for `sales_orders`, and `data/raw/_state/watermarks.json` holds the second run's cutoff for every table.

## Out of scope

Key snapshots and control totals are added in stage 5. Compaction of small raw files is deferred; record it under "Deferred" with the volume at which it starts to matter.
