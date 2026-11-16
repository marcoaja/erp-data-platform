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

## Deferred

- Compaction of small raw files. Every run writes at most one file per table; at a five-minute schedule that is about 288 files per table per day, and listing and reading them starts to cost noticeably around tens of thousands of files per table (roughly a few months). Compact per `extract_date` partition then.
