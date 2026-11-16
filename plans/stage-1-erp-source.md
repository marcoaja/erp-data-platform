# Stage 1: ERP source and simulator

**Goal.** A Postgres database that looks and behaves like a small ERP: it holds 90 days of history and keeps changing on its own.

**Depends on.** Stage 0.

**Human prerequisites.** None.

The table definitions and the simulator's behaviours are specified under "ERP source" in [ARCHITECTURE.md](ARCHITECTURE.md). This stage covers the five core tables; `inventory` arrives in stage 4.

## Tasks

- [x] **Write the migration runner.** `erp db migrate` applies the SQL files in `src/erp_platform/erp/migrations/` in filename order, each in its own transaction, and records the filename in `erp.schema_migrations`.
  Done when: running it twice applies nothing the second time, and a failing migration leaves no partial change.
- [x] **Write `001_initial.sql`.** Schema `erp`, the five core tables with their constraints and foreign keys, the `set_updated_at` trigger function attached to every table, and an index on each `updated_at`.
  Done when: a pytest updates a row in each table and sees `updated_at` advance without the statement setting it.
- [x] **Create the reader role.** After applying migrations, `erp db migrate` ensures a login role named by `ERP_READER_USER` exists with the configured password, with `usage` on schema `erp` and `select` on its tables, including tables created later (`alter default privileges`). Role DDL takes no bind parameters, so compose the statements with `psycopg.sql`.
  Done when: a pytest connects as the reader, reads a table, and is refused an `insert`; a table added by a later migration is readable without another grant.
- [x] **Write `erp seed`.** Deterministic for a given seed: 30 dealers (10 per country), 500 parts across 8 machine models, 2,000 customers with locale-appropriate names, and 90 days of orders in every status with consistent timestamps. Add `faker` as a dependency. Each seeding step is a no-op when its table already has rows.
  Done when: a pytest asserts the row counts, that every shipped order has `shipped_at >= ordered_at`, and that a second run changes nothing.
- [x] **Write `erp simulate`.** One tick performs the behaviours listed for stage 1 in the architecture, each in its own transaction. `--ticks N` runs N ticks and exits; `--interval S` loops with S seconds between ticks and stops cleanly on SIGINT and SIGTERM. `--seed` fixes the random generator.
  Done when: a pytest runs 20 ticks and asserts that new orders exist, at least one order advanced a status, at least one part's price changed, and at least one older order line was corrected.
- [x] **Order prices follow list prices.** A line's `unit_price` is the part's current list price converted with a fixed per-currency constant, less a random discount of up to 15%. The constants live beside the simulator.
  Done when: a pytest finds every `unit_price` within the expected band for its currency.
- [x] **Extend CI** to run migrations before pytest.
  Done when: the CI commands pass locally in a fresh database.

## Acceptance

```bash
docker compose up -d --wait postgres
uv run --env-file .env erp db migrate
uv run --env-file .env erp seed
uv run --env-file .env erp simulate --ticks 50 --seed 7
uv run --env-file .env pytest
uv run ruff check . && uv run ruff format --check .
```

After these commands, `select status, count(*) from erp.sales_orders group by 1` returns rows for all five statuses.

## Out of scope

Hard deletes, inventory, and schema changes are introduced in stages 4 and 5, where the pipeline learns to handle them.
