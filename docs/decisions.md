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

## Deferred

- (none yet)
