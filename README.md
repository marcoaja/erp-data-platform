# ERP Parts & Sales Data Platform

A portfolio data-engineering project. A simulated ERP in Postgres feeds an incremental pipeline into a dbt-modelled warehouse (DuckDB first, Snowflake last), and a reconciliation step proves the warehouse matches the source.

## Scenario

A fictional agricultural-machinery manufacturer sells spare parts through dealers in Japan, Indonesia, and Thailand. Its ERP records orders and stock. Management needs reports that put no load on the operational database.

The warehouse answers three business questions:

1. Which dealers risk running out of a part within seven days? Answered by `rpt_stockout_risk` (`transform/analyses/q1_stockout_risk.sql`).
2. How long does order fulfilment take, per dealer and per region? Answered by `fct_orders` with `dim_dealer` (`transform/analyses/q2_fulfilment_time.sql`).
3. What are parts sales per machine model, in one currency (JPY)? Answered by `fct_sales.amount_jpy`, converted with `fx_rates_daily` (`transform/analyses/q3_sales_by_machine_model.sql`).

**All data in this project is synthetic.** The value of the project is how the pipeline handles change: late updates, deletes, price history, schema changes, and proof that the warehouse matches the source.

## Quickstart

Requires Docker Desktop, [uv](https://docs.astral.sh/uv/), and Git.

```bash
cp .env.example .env                       # placeholder values work as-is
uv sync                                    # installs Python 3.12 and dependencies
docker compose up -d --wait postgres       # starts Postgres 17 on 127.0.0.1:5432
uv run --env-file .env erp db ping         # prints the Postgres version
uv run --env-file .env erp db migrate      # creates the erp schema and the reader role
uv run --env-file .env erp seed            # 30 dealers, 500 parts, 2,000 customers, 90 days of orders
uv run --env-file .env erp simulate --ticks 10   # or --interval 5 to keep the ERP changing
uv run --env-file .env erp extract         # writes changed rows to data/raw/ as Parquet
uv run --env-file .env erp fx              # fetches daily JPY exchange rates (public API, no key)
uv run --env-file .env erp run             # extract, fx, dbt build into data/warehouse.duckdb, then publish to data/serving/
uv run --env-file .env erp publish         # re-export only (erp run already does this); does not refresh the last-success time
uv run --env-file .env streamlit run dashboard/app.py   # dashboard; needs only data/serving/
```

Checks:

```bash
uv run ruff check .
uv run ruff format --check .
uv run --env-file .env pytest              # needs Postgres running
```

Design, data contracts and stage plans live in [plans/](plans/); trade-offs are logged in [docs/decisions.md](docs/decisions.md).
