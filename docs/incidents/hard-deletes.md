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
