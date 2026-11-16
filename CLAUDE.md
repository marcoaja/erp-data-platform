# ERP Parts & Sales Data Platform

Portfolio data-engineering project. A simulated ERP (Postgres) feeds an incremental pipeline into a dbt-modelled warehouse (DuckDB first, Snowflake last), and a reconciliation step proves the warehouse matches the source.

## Where things are

- `plans/README.md`: stage order and the execution protocol. Read it before starting a stage.
- `plans/ARCHITECTURE.md`: data contracts, repository layout, decided trade-offs. Read it before writing code.
- `docs/decisions.md`: running log of trade-offs. Append an entry whenever you choose between real alternatives.

## Engineering rules

- **KISS.** Build the simplest design that passes the stage's acceptance checks.
- **YAGNI.** Build what the current stage's tasks name. Ideas for later go under "Deferred" in `docs/decisions.md`.
- **Duplicate before you abstract.** Extract a helper at the third real occurrence, and only when the helper reads simpler than the copies.
- **Comments explain why.** A comment states a constraint, a trade-off, or a gotcha the code cannot express. Names and types carry the what. Public functions get a one-line docstring only when the signature leaves the contract unclear.
- **Fail loudly.** Exceptions propagate to the CLI entry point, which logs, alerts, and exits non-zero. Catch an exception only where the code recovers, and make the recovery explicit.
- **Idempotent commands.** Every command is safe to run twice.
- **Configuration comes from the environment** through `config.py`. `.env.example` lists every variable. Secrets stay out of git.
- **Types.** Timestamps are `timestamptz` in UTC. Money is `numeric` / `Decimal`. Python functions carry type hints.
- **SQL style.** Lowercase keywords, CTEs in the order import → logic → final select, explicit column lists in marts, one grain per model stated in its YAML description.
- **Portable dbt SQL.** Every model runs unchanged on DuckDB and Snowflake. Use dbt cross-database macros where dialects differ.
- **Tests exercise behaviour** against real Postgres and a real filesystem: idempotency, late updates, deletes, schema changes.
- **Logging** uses the `logging` module: one line per meaningful event, with row counts.
- **Dependencies.** Add one with `uv add` when the standard library would need more than about 30 lines to do the job. Commit `uv.lock`.
- **Current docs first.** dbt-duckdb, DuckDB, and Snowflake change quickly. Check the current documentation before using an API you have not used in this repo.
- **Commits.** Conventional Commits, one logical change each, checks green. Commit locally; pushing is the human's call.
- **Language.** Everything in the repository is written in English.
