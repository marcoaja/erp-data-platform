# Stage 0: Foundation

**Goal.** A repository where one command starts Postgres, one command proves the application can reach it, and CI checks every push.

**Depends on.** Nothing.

**Human prerequisites.** Docker Desktop, `uv`, and Git installed.

## Tasks

- [x] **Initialise the repository.** `git init`; `.gitignore` covering `.env`, `data/`, `.venv/`, dbt `target/` and `logs/`, `__pycache__/`.
  Done when: `git status` shows no ignored artefact as untracked.
- [x] **Create the Python project with uv.** Package `erp_platform` in `src/` layout, Python 3.12 pinned in `.python-version`, console script `erp = erp_platform.cli:main`. Runtime dependency: `psycopg[binary]`. Dev dependencies: `ruff`, `pytest`.
  Done when: `uv sync` succeeds from a clean clone and `uv.lock` is committed.
- [x] **Configure ruff** in `pyproject.toml`: formatter plus lint rule sets `E`, `F`, `I`, `B`, `UP`, `SIM`, line length 100.
  Done when: `uv run ruff check .` and `uv run ruff format --check .` pass.
- [x] **Write `config.py`.** A frozen dataclass `Settings` and a `load_settings()` that reads the Postgres variables from the environment and raises a clear error naming the first missing variable.
  Done when: a pytest covers the happy path and the missing-variable error.
- [ ] **Write `cli.py`.** `argparse` subcommands, logging configured once, and a top-level handler that logs the exception and exits with status 1. Implement `erp db ping`.
  Done when: `erp db ping` prints the Postgres version and exits 0; with Postgres stopped it logs the error and exits 1.
- [ ] **Write `compose.yaml`.** Service `postgres` on image `postgres:17`, credentials from `.env`, a health check using `pg_isready`, a named volume, a memory limit of 512 MB, and the port published on `127.0.0.1` only.
  Done when: `docker compose up -d --wait postgres` returns healthy.
- [ ] **Write `.env.example`** with every variable from the Configuration table that this stage uses, with safe placeholder values.
  Done when: copying it to `.env` unchanged is enough to run the acceptance commands.
- [ ] **Write the initial `README.md`.** Scenario, the three business questions, a statement that the data is synthetic, and a quickstart of the commands that exist so far.
  Done when: a reader can reach a passing `erp db ping` using only the README.
- [x] **Create `docs/decisions.md`** with two sections, "Decisions" and "Deferred", and one entry format: date, decision, alternatives considered, reason.
  Done when: the file exists with the choice of uv and ruff recorded as the first entry.
- [ ] **Add CI.** `.github/workflows/ci.yml` on push and pull request: install uv, `uv sync`, ruff check, ruff format check, pytest with a `postgres:17` service container.
  Done when: the workflow file passes `actionlint` or an equivalent syntax check, and the same commands pass locally.

## Acceptance

```bash
docker compose up -d --wait postgres
uv run --env-file .env erp db ping
uv run ruff check .
uv run ruff format --check .
uv run --env-file .env pytest
```

## Out of scope

Database tables, dbt, object storage, and deployment files belong to later stages.
