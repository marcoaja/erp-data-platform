# Stage 3: Warehouse with dbt and DuckDB

**Goal.** `erp run` turns the raw layer into a tested star schema, with dealer and part history preserved, on DuckDB.

**Depends on.** Stage 2.

**Human prerequisites.** None.

The layers, model list, grains, SCD2 rules, and test strategy are specified under "Warehouse" in [ARCHITECTURE.md](ARCHITECTURE.md). Build the models marked stage 3.

## Tasks

- [ ] **Create the dbt project** in `transform/`. Add `dbt-core`, `dbt-duckdb`, and `duckdb` as dependencies, pinned to the dbt 1.x line. `profiles.yml` lives in `transform/`, reads everything from environment variables, and defines target `local` writing to `WAREHOUSE_PATH`. Install `dbt_utils` through `packages.yml`.
  Done when: `uv run --env-file .env dbt debug --project-dir transform --profiles-dir transform` passes.
- [ ] **Declare the sources.** One source `erp` whose tables read `<RAW_URI>/<table>/*/*.parquet` through `external_location` with `union_by_name = true`. The source carries no target-specific logic beyond that property, so it resolves to schema `RAW` on Snowflake later.
  Done when: `select count(*) from {{ source('erp', 'parts') }}` compiles and runs.
- [ ] **Write the five staging models** at version grain, as specified. Use `qualify` for the duplicate removal and the `is_current` flag; both DuckDB and Snowflake support it.
  Done when: each model has `unique` on the combination (`id`, `updated_at`) and `not_null` on its key columns, and the tests pass.
- [ ] **Write `dim_date`, `dim_customer`, `dim_dealer`, `dim_part`.** The two SCD2 dimensions follow the rules in the architecture.
  Done when: a dbt unit test feeds three versions of one part and expects three rows with contiguous, non-overlapping intervals and one `is_current`.
- [ ] **Write `fct_sales` and `fct_orders`.** `fct_sales` resolves `dealer_key` and `part_key` as of `ordered_at` and carries the list price in force at that time.
  Done when: a dbt unit test places an order between two price versions and expects the earlier version's key and price; `relationships` tests from both facts to every dimension pass.
- [ ] **Add the cross-model invariants** as singular tests: SCD2 intervals of one `id` never overlap, and every `fct_sales` row resolves exactly one dealer version and one part version.
  Done when: both tests pass, and each fails when you temporarily break the join condition.
- [ ] **Document every model** in YAML: a description stating the grain, and a description for each column a reader could misread.
  Done when: no mart model lacks a grain statement.
- [ ] **Write `erp transform` and `erp run`.** `erp transform` runs `dbt build` as a subprocess for `DBT_TARGET` and fails when dbt fails. `erp run` executes extract then transform and stops at the first failure.
  Done when: `erp run` twice in a row leaves identical row counts in every mart.
- [ ] **Add SQL linting.** `sqlfluff` with the dbt templater and the DuckDB dialect, configured for lowercase keywords.
  Done when: `uv run sqlfluff lint transform/models` passes.
- [ ] **Extend CI** with an end-to-end job: migrate, seed, simulate 20 ticks, `erp run`, simulate 5 ticks, `erp run`.
  Done when: the job's commands pass locally from an empty database and an empty `data/` directory.

## Acceptance

```bash
uv run --env-file .env erp run
uv run --env-file .env erp simulate --ticks 20 --seed 7
uv run --env-file .env erp run
uv run sqlfluff lint transform/models
uv run --env-file .env pytest
```

After these commands, this query against the warehouse file returns one row per machine model:

```sql
select p.machine_model, sum(s.amount_local) as amount_local, s.currency_code
from marts.fct_sales s
join marts.dim_part p using (part_key)
group by all
```

## Out of scope

Currency conversion, inventory, and reconciliation belong to stages 4 and 5. Incremental materializations and dbt snapshots are decided against in the architecture.
