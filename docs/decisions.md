# Decisions

Entry format: date, decision, alternatives considered, reason.

## 2026-11-16: uv and ruff for tooling

- **Decision.** uv manages Python, dependencies and the lockfile; ruff does linting and formatting.
- **Alternatives.** pip with venv and requirements files; poetry; black plus flake8 plus isort.
- **Reason.** uv pins the interpreter and produces a committed `uv.lock` with one tool, and ruff replaces three formatters and linters with one fast config in `pyproject.toml`.

## 2026-11-16: `load_settings` takes an optional mapping

- **Decision.** `load_settings(env=None)` reads `os.environ` by default but accepts a mapping.
- **Alternatives.** Always read `os.environ` and have tests use `monkeypatch.setenv`.
- **Reason.** Passing a dict keeps the configuration tests free of global state at the cost of one parameter.

## 2026-11-16: CI sets Postgres variables as workflow environment

- **Decision.** CI exports the same placeholder `POSTGRES_*` values as `.env.example` in the job `env`, rather than copying a `.env` file.
- **Alternatives.** `cp .env.example .env` and run with `--env-file`.
- **Reason.** GitHub service containers are configured in the workflow anyway, and plain environment variables exercise `config.py` the way production will.

## 2026-11-16: Tests create throwaway databases from templates

- **Decision.** pytest creates `erp_test_<random>` databases next to the configured one, clones them from a migrated (and a seeded) template database, and drops them afterwards.
- **Alternatives.** Run tests against the `erp` database and truncate between tests; one shared test database.
- **Reason.** Tests never touch the developer's seeded data, and `create database ... template` makes a fresh seeded copy cheap. It needs a role with `createdb`, which the compose and CI owner role has.

## 2026-11-16: Seeded rows carry historical timestamps

- **Decision.** Seed sets `created_at`/`updated_at` explicitly: master data 90 days ago, orders and lines at their business timestamps. Only later changes get `now()` from the trigger.
- **Alternatives.** Let every seeded row default to the seed time.
- **Reason.** Stage 3's SCD2 and as-of joins need old versions to predate later changes, and a watermark extract over the seed looks like real history. Tests detect corrections as `updated_at > created_at`.

## 2026-11-16: Order numbers come from a sequence default

- **Decision.** `sales_orders.order_number` defaults to `'SO-' || lpad(nextval('erp.order_number_seq'), 7, '0')`.
- **Alternatives.** The simulator computes the next number in Python.
- **Reason.** The database owns number generation like a real ERP, and no code can collide or race.

## 2026-11-16: Check constraints on order timestamps

- **Decision.** `shipped_at >= ordered_at`, and `delivered_at` requires `shipped_at` and is not earlier than it, as table checks.
- **Alternatives.** Rely on the simulator alone.
- **Reason.** The source then cannot hold inconsistent history, and the seed/simulator tests fail loudly if they try.

## 2026-11-16: Fixed FX constants and regions live in `simulate.py`

- **Decision.** `FX_PER_JPY` (IDR 105, THB 0.23) and `REGIONS` sit beside the simulator; the seed imports them.
- **Alternatives.** A separate reference module.
- **Reason.** Two users do not justify a module. Stage 4 fetches real rates for reporting; these constants only generate source prices.

## 2026-11-16: pytest base temp inside the project

- **Decision.** `addopts = "--basetemp=.pytest_tmp"` (git-ignored).
- **Alternatives.** Default system temp directory.
- **Reason.** The system temp directory was not writable on the development machine, which broke `tmp_path`.

## 2026-11-16: Run ids never repeat; a same-second run waits

- **Decision.** If the new cutoff formats to the same `run_id` as the last committed run, extract rolls back, sleeps to the next second, and takes a fresh snapshot.
- **Alternatives.** Microsecond run ids (changes the documented format); overwrite on collision.
- **Reason.** A same-second run would overwrite the first run's files after the watermark committed them, losing rows. Tests and impatient operators hit this; production schedules do not.

## 2026-11-16: Local writes go through a temporary name and a rename

- **Decision.** `Storage` writes local Parquet and JSON to `<name>.tmp` and renames; S3 writes go straight to the final key.
- **Alternatives.** Write in place everywhere.
- **Reason.** A crash mid-write must not leave a truncated `watermarks.json` or Parquet file that downstream reads. Object stores only publish an object once the upload completes. Both write paths share the pattern at two occurrences, so no helper yet.

## 2026-11-16: `RAW_URI` is required, other new settings are optional

- **Decision.** `load_settings` fails when `RAW_URI` is missing; `EXTRACT_LOOKBACK_SECONDS` defaults to 300 and the `S3_*` variables default to unset (empty strings count as unset). CI sets `RAW_URI=data/raw`.
- **Alternatives.** Default `RAW_URI` in code.
- **Reason.** Every command loads the same settings, and a silent default would hide a mis-set environment on the VPS.

## 2026-11-16: Whole table read into memory per extract

- **Decision.** Each table's changed rows are fetched with `fetchall()` and written as one Parquet file.
- **Alternatives.** Server-side cursor with batched row groups.
- **Reason.** The first extract is 16,000 rows and takes 0.2 s. Batching is added when a single table passes about a million rows.

## 2026-11-16: `valid_to` is null on the current dimension version

- **Decision.** The open interval of an SCD2 row has `valid_to is null`; as-of joins use `valid_from <= t and (valid_to is null or t < valid_to)`.
- **Alternatives.** A far-future sentinel such as `9999-12-31`.
- **Reason.** Null states "no end" honestly and needs no magic date that differs in meaning per warehouse. The cost is one `is null` in each as-of join, kept identical in `fct_sales`, `fct_orders`, and the invariant test.

## 2026-11-16: dbt schemas are used as configured; staging is materialized as tables

- **Decision.** A `generate_schema_name` override uses `staging` and `marts` verbatim instead of dbt's `<target schema>_<custom>`. Staging is `table`, not `view`.
- **Alternatives.** Default naming (`main_marts`); staging views.
- **Reason.** The plan's acceptance query reads `marts.fct_sales`, and Snowflake will use the same schema names. Staging views would store the raw path inside the warehouse file; tables keep the file self-contained. Volume is small.

## 2026-11-16: DuckDB session time zone is pinned to UTC

- **Decision.** The `local` profile sets `settings: {TimeZone: UTC}`.
- **Alternatives.** A dialect-specific `at time zone` expression in each model.
- **Reason.** `cast(timestamptz as date)` follows the session time zone in DuckDB, which would make `order_date` depend on the machine running dbt. One profile setting keeps the model SQL portable. The Snowflake profile must set the equivalent (`timezone: UTC`) in stage 7.

## 2026-11-16: `WAREHOUSE_PATH` is required; `DBT_TARGET` defaults to `local`

- **Decision.** `load_settings` fails without `WAREHOUSE_PATH`. `erp transform` passes `RAW_URI`, `WAREHOUSE_PATH`, and `DBT_TARGET` to dbt explicitly. `profiles.yml` and the source still carry fallbacks, for tooling only.
- **Alternatives.** Let dbt read the process environment; default the path in code.
- **Reason.** One source of truth for the pipeline, and tests can point a run at temporary paths. The fallbacks let `sqlfluff` and `dbt debug` run without an env file, as the stage's acceptance commands require.

## 2026-11-16: dbt runs as a subprocess of `python -m dbt.cli.main`, with `deps` on first use

- **Decision.** `erp transform` shells out to the dbt in the same virtual environment and runs `dbt deps` only when `transform/dbt_packages` is missing.
- **Alternatives.** dbt's programmatic `dbtRunner`; `deps` on every run.
- **Reason.** A subprocess keeps dbt's own logging and exit code, which the stage asks for. `deps` on every run needs the network and rewrites the lock file for no gain; `package-lock.yml` pins the version.

## 2026-11-16: Invariant tests recompute resolution from the fact's own keys

- **Decision.** `fct_sales_resolves_one_version` checks the interval of the dealer and part version that each fact row points at, rather than repeating the join.
- **Alternatives.** Rebuild the as-of join inside the test.
- **Reason.** A test that copies the join shares its bug. Both invariants were confirmed to fail when the join upper bound or `valid_to` was removed.

## 2026-11-16: `fct_sales` and `fct_orders` keep cancelled orders

- **Decision.** Both facts carry `order_status`; cancelled rows are not filtered out.
- **Alternatives.** Drop cancelled orders in the facts.
- **Reason.** Fulfilment and sales marts in stage 4 choose their own filter, and a fact that hides rows cannot be reconciled against the source.

## 2026-11-16: `dim_date` spans 2020 to 2030 with a minimal column set

- **Decision.** A fixed date spine with year, month, day, and month start.
- **Alternatives.** Derive the range from the data; add weekday and fiscal columns.
- **Reason.** A fixed range never makes a fact miss its date after a late arrival. Extra columns wait for a stage that needs them.

## 2026-11-16: Inventory is seeded from parts each dealer has ordered; replenishment state is derived

- **Decision.** `erp seed` stocks each dealer with up to 60 parts it has ordered in the seeded history, at 20% to 300% of a reorder point of 5 to 20 units. The simulator decrements stock when an order ships (never below zero) and restocks a row below its reorder point 3 to 6 ticks after it was first seen low. The pending deliveries live in memory and are rediscovered from stock levels each tick.
- **Alternatives.** Random parts per dealer; a `replenish_at` column or a purchase-order table.
- **Reason.** Sales are spread over 15,000 dealer and part pairs, so stock on random parts would never show a cover below seven days. Stocking sold parts makes the stockout report non-trivial. A restart loses no delivery because the pending set is recomputed from the rows, and the contract keeps its four columns.

## 2026-11-16: Extract treats a new table as a missing watermark

- **Decision.** `inventory` joined `TABLES` with no other change. A table without a watermark is read in full, and the other tables keep reading from their own watermarks.
- **Alternatives.** A one-off backfill command.
- **Reason.** The stage 2 protocol already defines this case, and a test now pins it.

## 2026-11-16: `erp fx` keeps its own state in the raw files, and revises seven days back

- **Decision.** The next start date is the latest `date` found in `fx_rates/`, minus seven days; the first run starts at the earliest `ordered_at` (UTC date). A run that would reuse a committed file name waits for the next second. `rate` is stored as `decimal(18,8)`, parsed from the JSON as `Decimal`. A request has a 10 second timeout and one retry; failure raises `FxUnavailable`, and only `erp run` turns it into a warning.
- **Alternatives.** A date in `watermarks.json`; floats.
- **Reason.** `watermarks.json` holds cutoff timestamps that `erp extract` turns into run ids, so a date there would corrupt that logic. The seven-day re-read is shorter than the first run's window, so overwriting a committed file would lose dates, hence the wait. Exact decimals keep binary float noise out of reported amounts.

## 2026-11-16: A first `erp run` with no rates fails; later runs forward-fill

- **Decision.** If the API is down before any rate has ever been stored, `dbt build` fails because the `fx_rates` source matches no files. The soft failure applies once at least one rate file exists.
- **Alternatives.** Create an empty typed file on startup so the model builds with no rates.
- **Reason.** With no rates every `amount_jpy` is null, so the pipeline cannot give correct output anyway and failing loudly is the honest result.

## 2026-11-16: The real API publishes weekend rates; forward filling still matters

- **Decision.** `fx_rates_daily` forward-fills from the last published rate through today, as specified.
- **Alternatives.** Rely on the API having every day.
- **Reason.** A live request showed Frankfurter returns every calendar day, including weekends, but today's rate may not exist yet and a revision window may leave gaps. The local fake server in the tests skips weekends so forward filling is exercised.

## 2026-11-16: `today()` macro and a UTC-day spine bounded by today

- **Decision.** `fx_rates_daily`, `fct_inventory_daily` and `rpt_stockout_risk` read the current day from a `today()` macro wrapping `dbt.current_timestamp()`; unit tests override the macro.
- **Alternatives.** `current_date` in each model; a `var`.
- **Reason.** `current_date` cannot be overridden in a unit test, so the forward-filled spine would run to the real date and break the expected rows. The macro is referenced directly by each model, which is what dbt's override mechanism requires.

## 2026-11-16: Daily inventory keeps natural ids; the report is keyed on current dimension rows

- **Decision.** `fct_inventory_daily` carries `dealer_id` and `part_id`, not SCD2 keys. `rpt_stockout_risk` maps `fct_sales` keys back to ids through the dimensions and attaches current dealer and part attributes.
- **Alternatives.** Resolve `dealer_key` and `part_key` per day.
- **Reason.** The stage names the grain as dealer, part, day and tests uniqueness on those ids. A stock report wants today's region and part name, so a per-day as-of join would add cost and no answer.

## 2026-11-16: `amount_jpy` is cast to `decimal(18, 2)` after dividing

- **Decision.** `cast(quantity * unit_price / rate as decimal(18, 2))`.
- **Alternatives.** Divide decimals without a cast.
- **Reason.** DuckDB divides decimals in floating point. The cast returns an exact two-decimal amount on both DuckDB and Snowflake, at the cost of rounding each line to the second decimal before summing.

## 2026-11-16: `reconciliation_runs` is the one incremental model, and a rebuild restarts its history

- **Decision.** `reconciliation_runs` is incremental with `unique_key = [run_id, table_name, metric]`, `delete+insert`, and `full_refresh = false`; every other model stays a full-refresh table. Deleting the DuckDB file and running `erp transform` rebuilds every mart to the same row counts and checksums (`tests/test_rebuild.py`), except `reconciliation_runs`, which restarts with one run.
- **Alternatives.** Rebuild it as a table from every `control_totals` file, which keeps history across rebuilds but compares old totals against the current warehouse and so reports old runs as mismatches whenever data has changed since; or keep history outside the warehouse.
- **Reason.** A run's result is a fact about the warehouse at that moment, so it cannot be recomputed later. `full_refresh = false` stops `dbt build --full-refresh` from wiping the history by accident. `delete+insert` makes a repeated `erp transform` of the same extract replace its own rows. The cost is that the history is only as durable as the warehouse file, which the architecture already treats as disposable.

## 2026-11-16: Control totals are `decimal(38,2)` and compared for exact equality

- **Decision.** The extract writes `row_count` for every table, `sum_quantity` and `sum_amount_local` (`sum(quantity * unit_price)`) for `order_lines`, and `sum_quantity_on_hand` for `inventory`, all as `decimal(38,2)`. The warehouse side recomputes the same expressions over staging rows that are current and not deleted, and a metric matches only when the values are equal.
- **Alternatives.** Separate integer and decimal columns; a tolerance.
- **Reason.** One value type keeps the file and the model simple. Both sides are exact decimals, so any difference is a real difference. The expressions exist twice (in `extract.py` and in the model); the model's comment points at the constant.

## 2026-11-16: A failed `dbt build` prints the mismatching rows, then re-raises

- **Decision.** `transform()` catches the failed build only to run `dbt show --select reconciliation_matches_source`, which prints the table and metric, and then re-raises.
- **Alternatives.** Read the warehouse with DuckDB in Python after a failure; `store_failures`.
- **Reason.** dbt names a failing test and its row count but not its rows. `dbt show` goes through the adapter, so the same code works on Snowflake, where a direct DuckDB read would not.

## 2026-11-16: Deletes are found by a full key snapshot, and deleted rows are hidden, not removed

- **Decision.** Every run overwrites `_keys/<table>/latest.parquet` with all live ids from the extract snapshot. Staging sets `is_deleted` on every version of an id that is missing from it; facts, `dim_customer`, `fct_inventory_daily`, and the reconciliation warehouse side exclude deleted rows. The SCD2 dimensions keep the history and close the last interval at the `_extracted_at` of the last version, with `is_current` false.
- **Alternatives.** Soft deletes in the source; log-based CDC; closing the interval at the time the key file was written (it moves on every run, so `valid_to` would never be stable).
- **Reason.** See `docs/incidents/hard-deletes.md`. The last extraction time of the last version is the latest moment the row is known to have existed, and it does not change once the row leaves the lookback window. The keys file is written before the watermark commit; a crash in between leaves keys that are ahead of the data, which only flags rows that really are gone.

## 2026-11-16: Deletes in the simulator are opt-in and never empty an order

- **Decision.** `--with-deletes` deletes the last line (line number above 1) of up to three open (`placed`, `confirmed`) orders per tick. Without the flag, behaviour is unchanged.
- **Alternatives.** Always delete, as `ARCHITECTURE.md` first described; delete any line.
- **Reason.** The stage asks for a flag, and the earlier stages' tests and seeds should not change. Keeping at least one line means a deleted line never leaves an order with no lines, which no real ERP allows.

## 2026-11-16: `sales_channel` is drawn from the same random generator

- **Decision.** The simulator picks each new order's channel with the tick's `random.Random`.
- **Alternatives.** A separate generator seeded from the order number.
- **Reason.** One generator keeps a seed reproducible with the least code. It changes the random sequence for a given seed compared with stage 4; no test depended on a particular sequence.

## 2026-11-16: Schema check compares Arrow types, and an added column forces one full re-read

- **Decision.** `_state/schemas.json` stores `{table: {column: arrow type}}`. A removed or retyped column raises `SourceSchemaChanged` before any file is written; an added column is logged and the table is read in full on that run. The file is written after the data files and before the watermarks. Accepting a breaking change means deleting the table's entry from `schemas.json`.
- **Alternatives.** Postgres type names; no re-read, relying on a later change to a row to carry the column into raw; a `erp accept-schema` command.
- **Reason.** Arrow types are what the raw files carry, so they are what a reader of the files would notice. Without the re-read, a migration on a quiet table would leave raw with no file holding the new column and fail the first `dbt build` that selects it by name. Deleting an entry needs no new command; a command is deferred until accepting changes becomes routine.

## 2026-11-16: Alerting is not part of this stage

- **Decision.** A failed reconciliation or schema check exits non-zero through the existing CLI handler. Sending the alert is stage 6's `alerting.py`.
- **Reason.** The stage file names no alerting task, and `ALERT_WEBHOOK_URL` and `alerting.py` do not exist yet.

## 2026-11-16: Publish whole marts and keep the dashboard's joins in the dashboard

- **Decision.** `erp publish` exports `rpt_stockout_risk`, `fct_orders`, `dim_dealer`, `fct_sales`, `dim_part`, and `reconciliation_runs` unchanged. The dashboard runs the stage 4 analysis queries over them with in-memory DuckDB.
- **Alternatives.** Publish pre-joined report tables (one per question), which needs three new dbt models and tests.
- **Reason.** The published files stay the tested star schema and the dashboard SQL stays the analyses already verified in stage 4. The cost is a 700 KB `fct_sales` read per page load, which is small at this scale.

## 2026-11-16: The last successful run is a marker file written by `erp run`

- **Decision.** `erp run` writes `last_success.json` (`finished_at`, UTC) after `publish()` returns, which is after `dbt build` and its reconciliation test passed. `erp publish` alone exports the files and leaves the marker as it was.
- **Alternatives.** Writing it inside `publish()` (the first version: a standalone `erp publish` after a failed reconciliation advanced the marker); the files' modification times; a table in the warehouse; a row in Postgres.
- **Reason.** The marker must mean "a whole run, including reconciliation, succeeded"; only `run()` knows that. Modification times say when each file was written, not whether the run finished, and mix with partial publishes. A warehouse table would need the dashboard to open the warehouse (the lock this design avoids) and Postgres would make the dashboard depend on the ERP. The marker lives next to the data it describes and is replaced atomically like the data.

## 2026-11-16: Publish retries the rename on Windows

- **Decision.** The rename into place retries on `PermissionError` for up to five seconds.
- **Reason.** Windows refuses to replace a file a reader has open; POSIX does not. The dashboard's reads are short. The deployment host is Linux, so this only matters on the development machine, and a hard failure after five seconds still propagates.

## 2026-11-16: `SCHEDULE_INTERVAL_MINUTES` is a setting, not a constant

- **Decision.** The dashboard reads the schedule interval (default 30) from the environment through `load_dashboard_settings`, which needs no Postgres or warehouse variable.
- **Reason.** The staleness threshold must follow the cron entry, and the dashboard has to start without the variables `load_settings` requires.

## Deferred

- Compaction of small raw files. Every run writes at most one file per table; at a five-minute schedule that is about 288 files per table per day, and listing and reading them starts to cost noticeably around tens of thousands of files per table (roughly a few months). Compact per `extract_date` partition then.
- Log-based change data capture (for example Debezium on the Postgres write-ahead log). It would capture deletes without a key read, and the intermediate versions that two extracts collapse into one. It needs logical replication on the ERP and a connector to operate, which is more than this scale and the 4 GB VPS justify. Revisit when the full key read per run or the lost intermediate versions become the problem.
- Duplicate-customer matching. The ERP can hold the same customer twice under different ids; resolving that needs fuzzy matching and a survivorship rule, which does not serve any of the three business questions. Revisit when a question counts customers.
- An `erp accept-schema` command that edits `_state/schemas.json`. Revisit when accepting a schema change stops being rare.
