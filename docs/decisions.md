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

## Deferred

- (none yet)
