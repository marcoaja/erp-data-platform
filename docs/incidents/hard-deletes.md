# Incident: hard deletes in the ERP leave ghost rows in the warehouse

## What happened

The simulator was run with `--with-deletes`, which hard-deletes the last line of a few open orders on every tick (a user removing a line from an order that has not shipped). After 50 ticks, `erp run` extracted, transformed, and then failed on the reconciliation test:

```
$ uv run --env-file .env erp simulate --ticks 50 --seed 7 --with-deletes
$ uv run --env-file .env erp run
...
65 of 122 FAIL 3 reconciliation_matches_source
...
| run_id           | table_name  | metric           |       source_value |    warehouse_value | difference |
| ---------------- | ----------- | ---------------- | ------------------ | ------------------ | ---------- |
| 20261116T082954Z | order_lines | row_count        |          14,806.00 |          14,808.00 |       2.00 |
| 20261116T082954Z | order_lines | sum_quantity     |         153,415.00 |         153,436.00 |      21.00 |
| 20261116T082954Z | order_lines | sum_amount_local | 148,726,091,389.92 | 148,726,107,292.07 |  15,902.15 |
```

`source_value` is the total the extract took inside its own snapshot of Postgres. `warehouse_value` is the same total over the current rows in `stg_erp__order_lines`. The warehouse holds more order lines than the ERP, so every fact and report built on `order_lines` overstated sales. Nothing else failed: every other table reconciled, and every other test passed, which is why only a control total could find it.

The exact rows, found by comparing the warehouse's current line ids with `erp.order_lines`:

| order_line_id | order_id | line_number | part_id | quantity | unit_price |
|---|---|---|---|---|---|
| 13573 | 4541 | 2 | 270 | 2 | 89.16 |
| 13574 | 4541 | 3 | 462 | 19 | 827.57 |

Both lines were extracted by an earlier run, then deleted in the ERP. They are the 2 extra rows, 2 + 19 = 21 extra units and 2 x 89.16 + 19 x 827.57 = 15,902.15 extra currency units in the table above.

## Why a watermark cannot see a deleted row

`erp extract` selects rows where `updated_at` is greater than the watermark. A `delete` removes the row, and with it the only column the extract filters on. There is no row left to select, no new `updated_at` to compare, and the `before update` trigger never fires because there is no update. The raw layer is append-only, so the earlier version of the line stays in Parquet for ever, and staging treats the newest version of every id as current. A deleted row is therefore indistinguishable from a row that has not changed.

Only 2 of the 82 lines the simulator deleted surfaced. Most were created and deleted between two extracts, so the pipeline never saw them. A line is a ghost only when an extract captured it before the delete.

## The fix: a key snapshot per run

In the same `repeatable read` transaction as the change extract, `erp extract` now reads every live `id` of every table and overwrites `_keys/<table>/latest.parquet`. The file is a complete list of what exists in the ERP at the extract's cutoff.

- Staging joins each version to that file and sets `is_deleted` when its id is missing. The flag is on every version of the id, so it does not depend on which version is current.
- Facts (`fct_sales`, `fct_orders`, `fct_inventory_daily`), `dim_customer`, and the warehouse side of `reconciliation_runs` read `is_current and not is_deleted`.
- The slowly changing dimensions keep a deleted row's history but close its last interval, at the time that version was last extracted (the latest moment the row is known to have been alive), and `is_current` is false. A part or dealer cannot be deleted while orders reference it, so no table produces this today; the rule exists so that a dimension never keeps a live last version for a row the source no longer has.
- A dbt unit test (`fct_sales_leaves_out_a_deleted_line`) covers a deleted line, `dim_part_closes_the_last_interval_of_a_deleted_part` covers the dimension, and `test_hard_deleted_lines_leave_the_facts_and_the_totals_still_match` runs the whole pipeline against Postgres.

Raw stays append-only. The deleted line's versions are still in Parquet; the warehouse hides them, and a rebuild from raw and the latest keys file reproduces the same answer.

## Cost

One extra `select id from <table>` per table per run, read in the extract snapshot, and one small Parquet file per table overwritten. It scales with the size of the tables, not with the amount of change: at the current 15,000 order lines this is milliseconds, at hundreds of millions of rows it would dominate the run.

## Alternatives

- **Soft deletes in the source** (an `is_deleted` or `deleted_at` column set by the application instead of a `delete`). The delete becomes an update the watermark already sees and no key snapshot is needed. It requires the source system to change, which a data team rarely controls, and it does nothing about code paths that still run `delete`.
- **Log-based change data capture** (read the Postgres write-ahead log, for example with Debezium). It captures deletes as events, and also every intermediate version that two extracts can currently collapse into one. It needs logical replication privileges on the ERP, a connector to run, and offsets to manage, which is more than this pipeline's scale or the VPS justifies. It is recorded as deferred in `docs/decisions.md`.

## Result

With the fix in place, the same environment (the 82 deleted lines above, then 20 further ticks with `--with-deletes`) reconciles. Run `20261116T083552Z`:

```
| run_id           | table_name  | metric           |       source_value |    warehouse_value | difference | is_match |
| ---------------- | ----------- | ---------------- | ------------------ | ------------------ | ---------- | -------- |
| 20261116T083552Z | order_lines | row_count        |          15,308.00 |          15,308.00 |       0.00 | true     |
| 20261116T083552Z | order_lines | sum_amount_local | 154,946,271,841.83 | 154,946,271,841.83 |       0.00 | true     |
| 20261116T083552Z | order_lines | sum_quantity     |         158,442.00 |         158,442.00 |       0.00 | true     |
```

`dbt build` finished with `PASS=130 WARN=0 ERROR=0`, and 8 order lines are now flagged `is_deleted` in staging, including the two ghost lines 13573 and 13574 from the failing run. The failing run `20261116T082954Z` stays in `reconciliation_runs` as history, which is the point of keeping earlier runs.
