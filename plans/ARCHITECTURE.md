# Architecture and data contracts

This file is the specification for every stage. Once code exists, the code is the truth; a stage that changes a contract updates this file in the same commit.

## Scenario

A fictional agricultural-machinery manufacturer sells spare parts through dealers in Japan, Indonesia, and Thailand. Its ERP records orders and stock. Management needs reports that put no load on the operational database.

Business questions the warehouse answers:

- **Q1.** Which dealers risk running out of a part within seven days?
- **Q2.** How long does order fulfilment take, per dealer and per region?
- **Q3.** What are parts sales per machine model, in one currency (JPY)?

The ERP data is synthetic and the README says so. The project's value is how the pipeline handles change: late updates, deletes, price history, schema changes, and proof that the warehouse matches the source.

## Flow

```
simulator ──writes──> Postgres "erp" schema (OLTP)
                           │  erp extract   (incremental, watermark on updated_at)
                           ▼
                 raw layer: Parquet, append-only (local disk, then R2)
                           │  dbt build     (DuckDB, then Snowflake)
                           ▼
                 staging ──> marts (star schema, SCD2 dimensions)
                           │  erp publish
                           ▼
                 serving Parquet ──> Streamlit dashboard
```

## Repository layout

```
pyproject.toml  uv.lock  .python-version  .env.example
compose.yaml  Dockerfile  README.md  CLAUDE.md
src/erp_platform/
  cli.py            the `erp` console script
  config.py         Settings loaded from the environment
  storage.py        one filesystem interface for local paths and s3:// URIs
  erp/              migrations/*.sql, migrate.py, seed.py, simulate.py
  ingestion/        extract.py, fx.py
  pipeline.py       erp run: the ordered steps and failure handling
  alerting.py
transform/          dbt project (models/staging, models/marts, tests, analyses)
dashboard/app.py
infra/              cron, deploy script, snowflake/*.sql
tests/              pytest
docs/               decisions.md, runbook.md, incidents/
plans/
```

## Commands

`erp` is the only entry point. Each subcommand is idempotent.

| Command | Does | Stage |
|---|---|---|
| `erp db ping` | Connects and prints the Postgres version | 0 |
| `erp db migrate` | Applies pending SQL migrations in order | 1 |
| `erp seed` | Loads initial master data and 90 days of order history; each seeding step is a no-op when its table already has rows | 1 |
| `erp simulate --ticks N` / `--interval S` | Runs N business ticks and exits, or loops forever with S seconds between ticks | 1 |
| `erp extract` | Writes changed rows to the raw layer and advances the watermark | 2 |
| `erp transform` | Runs `dbt build` for the configured target | 3 |
| `erp run` | Runs the pipeline steps in order; exits non-zero on the first failure | 3 |
| `erp fx` | Fetches daily exchange rates into the raw layer | 4 |
| `erp publish` | Exports marts to serving Parquet | 6 |
| `erp snowflake-load` | Copies raw Parquet from the bucket into Snowflake `RAW` tables | 7 |

Local development runs natively with `uv run --env-file .env erp <command>` against Postgres in Docker.

## Configuration

Every variable is read in `config.py` and listed in `.env.example`.

| Variable | Meaning |
|---|---|
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB` | ERP database location |
| `POSTGRES_USER`, `POSTGRES_PASSWORD` | Owner role: migrations, seed, simulator |
| `ERP_READER_USER`, `ERP_READER_PASSWORD` | Read-only role used by `erp extract` |
| `RAW_URI` | Raw layer root: a local path or `s3://bucket/raw` |
| `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_REGION` | Object storage credentials; unset for local paths. Leaving the endpoint unset targets AWS S3 |
| `EXTRACT_LOOKBACK_SECONDS` | Overlap subtracted from the watermark; default 300 |
| `WAREHOUSE_PATH` | DuckDB file written by dbt |
| `SERVING_DIR` | Directory of published mart Parquet read by the dashboard |
| `DBT_TARGET` | `local`, `r2`, or `snowflake` |
| `ALERT_WEBHOOK_URL` | Discord webhook; alerting is skipped when unset |
| `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PRIVATE_KEY_PATH` | Stage 7 only |

## ERP source

Postgres schema `erp`. Conventions for every table:

- `id bigint generated always as identity primary key`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`, set by a `before update` trigger so the application cannot forget it
- an index on `updated_at`

| Table | Columns beyond the conventions |
|---|---|
| `dealers` | `dealer_code` unique, `name`, `country_code` (JP, ID, TH), `region`, `currency_code` (JPY, IDR, THB) |
| `customers` | `dealer_id` fk, `name`, `email`, `phone`, `city` |
| `parts` | `part_number` unique, `name`, `machine_model`, `category`, `list_price_jpy numeric(12,2)`, `is_active` |
| `sales_orders` | `order_number` unique, `dealer_id` fk, `customer_id` fk, `status` (placed, confirmed, shipped, delivered, cancelled), `currency_code`, `ordered_at`, `shipped_at`, `delivered_at` |
| `order_lines` | `order_id` fk, `line_number`, `part_id` fk, `quantity` > 0, `unit_price numeric(14,2)` in the order's currency; unique (`order_id`, `line_number`) |
| `inventory` (stage 4) | `dealer_id` fk, `part_id` fk, `quantity_on_hand` ≥ 0, `reorder_point`; unique (`dealer_id`, `part_id`) |

Schema changes ship as numbered SQL files in `src/erp_platform/erp/migrations/`, applied by `erp db migrate` and recorded in `erp.schema_migrations`.

### Simulator behaviour

One tick, driven by a seeded random generator:

- creates new orders with one to five lines
- advances existing orders one status step and stamps `shipped_at` / `delivered_at`
- cancels a small share of placed orders
- corrects the quantity of a line on an older order (a late update)
- changes `list_price_jpy` for a few parts
- occasionally moves a dealer to another region
- from stage 4: decrements inventory on shipment and replenishes low stock
- from stage 5: hard-deletes a few lines from open orders

## Raw layer

Append-only Parquet, written by `erp extract`.

```
<RAW_URI>/<table>/extract_date=YYYY-MM-DD/<run_id>.parquet   changed rows, all source columns
<RAW_URI>/_keys/<table>/latest.parquet                       every live id (stage 5), overwritten per run
<RAW_URI>/control_totals/extract_date=YYYY-MM-DD/<run_id>.parquet   (stage 5)
<RAW_URI>/_state/watermarks.json                             {"<table>": "<cutoff ISO timestamp>"}
<RAW_URI>/_state/schemas.json                                {"<table>": {"<column>": "<type>"}} (stage 5)
```

`run_id` is the run's cutoff in UTC, formatted `YYYYMMDDTHHMMSSZ`. Every row carries `_run_id` and `_extracted_at`.

### Extract protocol

1. Open one `repeatable read, read only` transaction as the reader role. Every table is read from the same snapshot.
2. `cutoff` is that transaction's `now()`.
3. For each table, select `*` where `updated_at > watermark - lookback`. A table with no watermark is read in full. `select *` is deliberate: new source columns flow into raw without a code change.
4. Build the Arrow schema from the cursor's column metadata, so every file of a table has identical types regardless of the values in it.
5. Write the Parquet files, then write `watermarks.json` last. The state file is the commit point.

Guarantees and their reasons:

- **At-least-once delivery.** A crash between step 5's writes re-extracts the same rows next run. Staging removes the duplicates, so a re-run changes nothing downstream.
- **Late commits are caught.** A transaction that started before the previous cutoff and committed after it has an `updated_at` below the watermark. The lookback overlap re-reads that window. A transaction open longer than the lookback is missed; reconciliation detects it.
- **Intermediate versions can be lost.** Two updates between extracts leave only the second in raw. Closing that gap needs log-based CDC, which is deferred.

## Warehouse

A dbt project in `transform/` with targets `local` (DuckDB over local raw files), `r2` (DuckDB over the bucket), and `snowflake`.

On DuckDB, sources read Parquet directly through dbt-duckdb's `external_location` with `union_by_name = true`, so files written before and after a schema change read together. On Snowflake, the same source names resolve to tables in the `RAW` schema.

### Staging

One model per source table, named `stg_erp__<table>`, at **version grain**: one row per (`id`, `updated_at`).

- renames and casts columns
- removes duplicate versions from overlapping extracts
- flags `is_current` on the newest version of each `id`
- from stage 5: flags `is_deleted` when the `id` is missing from the latest keys file

### Marts

| Model | Grain | Notes | Stage |
|---|---|---|---|
| `dim_date` | one row per calendar day | built from a date spine | 3 |
| `dim_dealer` | one row per dealer version | SCD2: `dealer_key`, `valid_from`, `valid_to`, `is_current` | 3 |
| `dim_part` | one row per part version | SCD2, tracks `list_price_jpy` and descriptive attributes | 3 |
| `dim_customer` | one row per customer | current values only | 3 |
| `fct_sales` | one row per order line | dealer and part keys resolved as of `ordered_at`; `amount_local`; `amount_jpy` from stage 4 | 3 |
| `fct_orders` | one row per order | status, hours from order to shipment and to delivery | 3 |
| `fx_rates_daily` | one row per currency per day | missing days filled forward from the last published rate | 4 |
| `fct_inventory_daily` | one row per dealer, part, day | last known stock per day | 4 |
| `rpt_stockout_risk` | one row per dealer and part | days of cover from trailing 28-day sales; at risk below 7 | 4 |
| `reconciliation_runs` | one row per run and table | source control totals against warehouse totals, `is_match` | 5 |

SCD2 dimensions are derived from the version history in staging with window functions: `valid_from` is the version's `updated_at`, `valid_to` is the next version's `updated_at`. The first known version of a row is valid from its `created_at`. Surrogate keys hash (`id`, `valid_from`).

Marts are materialized as tables and rebuilt in full on every run.

### Tests

- generic tests on every model: `unique` and `not_null` on keys, `relationships` from facts to dimensions, `accepted_values` on status and currency
- unit tests for the SCD2 window logic and the as-of join in `fct_sales`
- one singular test per invariant that spans models, for example SCD2 intervals of one `id` never overlap

## Serving

DuckDB allows one writing process per database file, so the dashboard never opens the warehouse file. `erp publish` exports the marts the dashboard needs to `<SERVING_DIR>/<model>.parquet`, writing to a temporary name and renaming, and the dashboard reads those files with an in-memory DuckDB connection.

## Orchestration and failure handling

`erp run` executes extract → fx → transform → publish. Host cron starts it inside a `flock` so two runs never overlap.

- A failed step stops the run, sends one alert naming the step and the error, and exits non-zero. The watermark stays where it was, so the next run retries the same window.
- An exchange-rate API failure is the one soft failure: the run continues on forward-filled rates and sends a warning.
- The dashboard shows the time of the last successful run and warns when it is stale.

## Decided trade-offs

| Decision | Chosen | Why | Revisit when |
|---|---|---|---|
| Change capture | `updated_at` watermark with lookback | Works with read-only access; simple to reason about | Intermediate versions or sub-minute latency matter: log-based CDC |
| Delete detection | Compare against a full key snapshot per run | Needs no change to the source system, which a data team rarely controls | Tables grow past what a full key read affords |
| SCD2 | Window functions over raw history | Rebuildable from raw on any warehouse, so the Snowflake migration reproduces the same history; dbt snapshots keep history only inside one warehouse | Raw history is pruned |
| Materialization | Full-refresh tables | Data is small; no incremental state to corrupt | A build takes longer than the schedule interval |
| Orchestrator | Host cron with `flock` | The VPS has 4 GB shared with other workloads | Steps need retries, backfills by date, or a dependency graph: Dagster |
| Extract engine | psycopg + pyarrow | Explicit control of the transaction snapshot and the Arrow schema | — |
| Object storage | Cloudflare R2 through the S3 API | Free at this volume; identical code targets AWS S3 by changing configuration | — |
| Dashboard source | Published Parquet | Avoids DuckDB's single-writer lock | The warehouse becomes a server database |
| Reconciliation | dbt model comparing control totals taken in the extract snapshot | Source and warehouse are compared at the same instant, so a busy ERP causes no false alarms | — |

## Verified external facts

Checked on 2026-11-16. Re-check before relying on them.

- PyPI: `dbt-core` 1.12.7, `dbt-duckdb` 1.11.1, `dbt-snowflake` 1.12.5; all need Python ≥ 3.10. `dbt-snowflake` requires `dbt-core < 2.0`, so the project stays on the 1.x line.
- dbt-duckdb sources accept `external_location` under `meta` or `config`. The value may be a function call such as `read_parquet('…/{name}/*/*.parquet', union_by_name = true)`; `{name}` is filled per table. Storage credentials go under `secrets` in the profile.
- DuckDB reaches R2 either with an `s3` secret plus an endpoint, or with its dedicated `r2` secret type (`KEY_ID`, `SECRET`, `ACCOUNT_ID`) and `r2://` URLs. Prefer the `s3` form so `RAW_URI` keeps one scheme everywhere; fall back to `r2` if the endpoint form fails.
- Snowflake reads R2 through an external stage: `url = 's3compat://<bucket>/<path>/'`, `endpoint = '<account_id>.r2.cloudflarestorage.com'`. Endpoints containing `r2.cloudflarestorage.com` are enabled by default. Directory tables and external tables on such stages need a manual refresh.
- Snowflake trial: 30 days or $400 of credits, no payment method needed. Masking policies need Enterprise edition.
- Cloudflare R2 free tier: 10 GB-month, 1 million Class A and 10 million Class B requests per month, free egress.
- Frankfurter: `https://api.frankfurter.dev/v2/rates?base=JPY&quotes=IDR,THB&from=YYYY-MM-DD&to=YYYY-MM-DD` returns `[{date, base, quote, rate}]` with no API key. `rate` is units of the quote currency per one JPY.
