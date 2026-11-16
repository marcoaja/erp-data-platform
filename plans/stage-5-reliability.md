# Stage 5: Reliability

**Goal.** The pipeline proves on every run that the warehouse matches the ERP, and it survives the three things that break naive pipelines: hard deletes, schema changes, and a lost warehouse.

**Depends on.** Stage 4.

**Human prerequisites.** None.

This stage is the project's centrepiece. Each incident below is worked in the same order: reproduce the failure, capture the evidence, fix it, show the check passing. The write-ups go in `docs/incidents/` and are what an interviewer will read.

Raw-layer paths are specified under "Raw layer" in [ARCHITECTURE.md](ARCHITECTURE.md).

## Part A: Reconciliation

- [x] **Write control totals during extract.** In the same snapshot transaction, compute per table: row count, and for `order_lines` the sum of `quantity` and of `quantity * unit_price`; for `inventory` the sum of `quantity_on_hand`. Write them to `control_totals/…/<run_id>.parquet` with columns `run_id`, `table_name`, `metric`, `value`.
  Done when: a pytest compares the file's values with the same queries run by hand in one transaction.
- [x] **Write `reconciliation_runs`.** For the latest `run_id`, compare each control total with the same metric computed from the current staging rows. Columns: `run_id`, `table_name`, `metric`, `source_value`, `warehouse_value`, `difference`, `is_match`. Materialize it incrementally keyed on (`run_id`, `table_name`, `metric`) so earlier runs stay as history.
  Done when: after `erp run` on a fresh environment every row has `is_match = true`.
- [x] **Fail the build on a mismatch.** A singular test selects the latest run's rows where `is_match` is false.
  Done when: editing one raw value by hand makes `erp run` exit non-zero and name the table and metric.

## Part B: Hard deletes

- [x] **Reproduce.** Add the hard-delete behaviour to the simulator behind a flag `--with-deletes`. Run ticks with it, then `erp run`.
  Done when: the reconciliation test fails for `order_lines`, and you have saved the failing rows as evidence.
- [x] **Write `docs/incidents/hard-deletes.md`, first half.** What happened, why a watermark cannot see a deleted row, the evidence.
  Done when: the document shows the actual mismatch figures.
- [x] **Fix with key snapshots.** In the extract snapshot, write every live `id` of each table to `_keys/<table>/latest.parquet`. Staging flags `is_deleted` for an `id` absent from that file. Facts, current-state dimensions, and the warehouse side of `reconciliation_runs` exclude deleted rows; SCD2 dimensions close the deleted row's last interval.
  Done when: the reconciliation test passes with `--with-deletes` running, and a dbt unit test covers a deleted line.
- [x] **Finish the incident document.** The fix, its cost (a full key read per table per run), and the alternatives: soft deletes in the source, and log-based CDC.
  Done when: the document ends with the passing reconciliation output.

## Part C: Schema evolution

- [x] **Reproduce the change.** A new migration adds a nullable `sales_channel` column to `erp.sales_orders`; the simulator starts filling it for new orders.
  Done when: `erp run` succeeds after the migration with no code change, proving that old and new raw files read together.
- [x] **Guard it with a test.** A pytest extracts, applies a migration that adds a column, extracts again, and runs `dbt build` successfully.
  Done when: the test passes and fails if `union_by_name` is removed from the source definition.
- [x] **Expose the column.** Add `sales_channel` to `stg_erp__sales_orders` and `fct_orders`, null for orders that predate it.
  Done when: `accepted_values` on the column passes with nulls allowed.
- [x] **Detect breaking changes.** `erp extract` stores each table's column names and types in `_state/schemas.json` and compares them at the start of every run. An added column is logged and accepted. A removed or retyped column raises an error naming the table and column before anything is written, because reading old and new files together would otherwise turn the change into silent nulls.
  Done when: a pytest drops a source column and sees the run fail with that column's name, and the watermark unchanged.
- [x] **Write `docs/incidents/schema-evolution.md`.** Which changes the pipeline absorbs, which it stops on, why, and how an operator accepts an intended breaking change.
  Done when: the accept procedure in the document works when followed in a pytest.

## Part D: Rebuild from raw

- [x] **Prove the warehouse is disposable.** Delete the DuckDB file and run `erp transform`.
  Done when: a pytest shows every mart has the same row count and the same key totals before and after, except `reconciliation_runs`, whose history restarts; record that exception in `docs/decisions.md`.

## Acceptance

```bash
uv run --env-file .env erp db migrate
uv run --env-file .env erp simulate --ticks 50 --seed 7 --with-deletes
uv run --env-file .env erp run
uv run --env-file .env pytest
uv run sqlfluff lint transform/models
```

After these commands, `select count(*) from marts.reconciliation_runs where not is_match` returns 0, and `docs/incidents/` holds two complete write-ups.

## Out of scope

Log-based CDC and duplicate-customer matching are deferred; record both with the reason.
