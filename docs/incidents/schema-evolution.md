# Incident: the ERP schema changes under the pipeline

The ERP is owned by someone else, and its tables change. This document covers what the pipeline absorbs, what it stops on, and how an operator accepts a change on purpose.

## Added columns: absorbed

A migration (`003_sales_channel.sql`) added a nullable `sales_channel` to `erp.sales_orders`, and the simulator began filling it for new orders. Nothing in the pipeline was changed first:

```
$ uv run --env-file .env erp db migrate
... applied migration 003_sales_channel.sql
$ uv run --env-file .env erp simulate --ticks 5 --seed 3 --with-deletes
$ uv run --env-file .env erp run          # exit 0, dbt build PASS=130 WARN=0 ERROR=0
```

Raw then held 11 `sales_orders` files: ten written before the migration without the column and one written after it with the column (7,856 rows in total, 40 of them with a channel: the orders created after the migration). This works for two reasons:

1. `erp extract` runs `select *`, so the new column flows into the next Parquet file without a code change.
2. The dbt source reads raw with `read_parquet(..., union_by_name = true)`, which unifies the columns of all files and fills the missing ones with null. Without it, DuckDB takes the columns of the first file and silently drops the rest. `test_old_and_new_raw_files_read_together_after_a_column_is_added` guards this: it extracts before the column exists, adds it with a migration, extracts again, and runs `dbt build`. Removing `union_by_name` from the source definition makes it fail with `Referenced column "sales_channel" not found`.

Two details make added columns safe in practice:

- **The column is exposed explicitly.** `stg_erp__sales_orders` and `fct_orders` select `sales_channel`, null for orders that predate it, and a dbt `accepted_values` test allows nulls.
- **A table with a new column is re-read in full once.** A staging model selects columns by name, so at least one raw file must carry the new column. After a migration on a quiet table no row would change, and no file would be written. `erp extract` therefore logs the addition (`source schema: table=... added columns=...`) and ignores the watermark for that table on that run. The cost is one extra read of one table; the duplicate versions it writes are removed by staging's deduplication.

## Removed and retyped columns: the run stops

`erp extract` records every table's column names and Arrow types in `_state/schemas.json` after each successful run, and compares the live schema with it at the start of the next one, in the same snapshot, before any file is written. If a stored column is gone or has a different type, the run raises an error that names the table and column and writes nothing, so the watermark and the raw layer stay as they were:

```
ERROR erp_platform: command failed: extract
erp_platform.ingestion.extract.SourceSchemaChanged: source schema changed: customers.phone was removed.
Nothing was written. To accept an intended change, follow docs/incidents/schema-evolution.md.
```

A retype reads `parts.list_price_jpy changed type from decimal128(12, 2) to decimal128(14, 2)`. `test_dropped_column_stops_the_run_before_anything_is_written` and `test_retyped_column_stops_the_run_and_names_both_types` cover both.

### Why these stop instead of being absorbed

With `union_by_name`, old files keep the column and new files lack it, so the union fills null. Every row extracted after the change reads as "no value", and a model that sums or groups on the column gives a plausible wrong answer. No test fails, and the reconciliation control totals do not cover the column. A retyped column has the same problem in a different form: the union has to pick one type for the column, and values can be cast or rejected without notice. A loud failure at the start of the run costs one operator decision. A silent one costs a wrong report that someone finds later.

## Accepting an intended breaking change

Do this when the change is deliberate, for example a column was retired on purpose:

1. **Update the dbt models first.** Stop selecting a removed column, or cast a retyped one in staging. A removed column still exists in old raw files, so models that keep selecting it build, with null for every new row.
2. **Delete the table's entry from `_state/schemas.json`.** The stored shape is the only thing the check compares; with no entry, the next run records the live shape and accepts it. Against local raw, or against the bucket with the same `S3_*` variables:

   ```
   uv run --env-file .env python -c "
   from erp_platform.config import load_settings
   from erp_platform.storage import open_storage
   s = open_storage(load_settings())
   m = s.read_json('_state/schemas.json')
   del m['customers']
   s.write_json('_state/schemas.json', m)"
   ```

3. **Optional: rewrite history.** To have the whole table re-extracted in the new shape, also delete its key from `_state/watermarks.json`. Raw is append-only and the old files stay, but staging keeps the newest copy of every version, so the new files win.
4. **Run `erp run`.** The extract records the new schema, and later runs compare against it.

Running these steps against a copy of the development database:

```
$ erp extract            # after: alter table erp.customers drop column phone
ERROR ... customers.phone was removed. Nothing was written.
$ python -c "...del m['customers']..."
removed customers from schemas.json
$ erp extract
INFO  extract table=customers rows=0 file=none
INFO  extract done run_id=20261116T084544Z tables=6 rows=500 duration=0.12s
```

`test_documented_accept_procedure_lets_the_run_continue` follows steps 2 and 4 in a pytest: it drops `customers.phone`, sees the failure, removes the stored schema, extracts, and builds the warehouse. Old customer versions keep their phone numbers; the version written after the change has a null phone.

## What is not covered

- A column added and dropped between two runs is invisible, because only the live schema is compared with the stored one.
- Renames look like a removal plus an addition, and stop the run; that is the right outcome, because a rename needs a decision.
- Type changes that keep the Arrow type, for example `varchar(20)` to `varchar(40)`, pass because the Parquet files are identical.
