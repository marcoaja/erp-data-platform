# ERP Parts & Sales Data Platform

A portfolio data-engineering project. A simulated ERP in Postgres feeds an incremental pipeline into a dbt-modelled warehouse (DuckDB first, Snowflake last), and a reconciliation step proves the warehouse matches the source.

## Scenario

A fictional agricultural-machinery manufacturer sells spare parts through dealers in Japan, Indonesia, and Thailand. Its ERP records orders and stock. Management needs reports that put no load on the operational database.

The warehouse answers three business questions:

1. Which dealers risk running out of a part within seven days?
2. How long does order fulfilment take, per dealer and per region?
3. What are parts sales per machine model, in one currency (JPY)?

**All data in this project is synthetic.** The value of the project is how the pipeline handles change: late updates, deletes, price history, schema changes, and proof that the warehouse matches the source.

## Quickstart

Requires Docker Desktop, [uv](https://docs.astral.sh/uv/), and Git.

```bash
cp .env.example .env                       # placeholder values work as-is
uv sync                                    # installs Python 3.12 and dependencies
docker compose up -d --wait postgres       # starts Postgres 17 on 127.0.0.1:5432
uv run --env-file .env erp db ping         # prints the Postgres version
```

Checks:

```bash
uv run ruff check .
uv run ruff format --check .
uv run --env-file .env pytest              # needs Postgres running
```

Design, data contracts and stage plans live in [plans/](plans/); trade-offs are logged in [docs/decisions.md](docs/decisions.md).
