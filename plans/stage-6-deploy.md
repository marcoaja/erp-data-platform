# Stage 6: Deploy

**Goal.** The pipeline runs unattended on the VPS against R2, a public dashboard shows its results, and a failure reaches a human within one run.

**Depends on.** Stage 5.

**Human prerequisites.**

- SSH access to the VPS and the hostname the dashboard will use.
- Whether the VPS already runs a reverse proxy, and which one.
- A Cloudflare R2 bucket and an API token scoped to that bucket with object read and write.
- A Discord webhook URL.

The VPS has 2 vCPU and 4 GB of RAM shared with unrelated workloads. Changes to those workloads or to an existing reverse proxy's configuration are the human's to make: write the snippet they need into the runbook.

The first deployment is run by the human from the runbook, unless the human's prompt for this stage tells you to run it.

Serving and failure handling are specified under "Serving" and "Orchestration and failure handling" in [ARCHITECTURE.md](ARCHITECTURE.md).

## Tasks

- [ ] **Point the raw layer at R2.** Add target `r2` to `profiles.yml` with the storage secret from the `S3_*` variables. Run the stage 2 storage tests against the bucket under a throwaway prefix.
  Done when: `erp run` with `RAW_URI=s3://<bucket>/raw` and `DBT_TARGET=r2` passes end to end from the development machine.
- [ ] **Write `erp publish`.** Export the marts the dashboard reads to `SERVING_DIR`, each written to a temporary name and renamed. Append it as the last step of `erp run`.
  Done when: a pytest reads a published file while a publish is in progress and never sees a partial file.
- [ ] **Write `alerting.py`.** One function that posts a message to `ALERT_WEBHOOK_URL` and does nothing when it is unset. `erp run` sends one alert per failed run naming the step, the error, and the `run_id`, and one warning for a soft failure.
  Done when: a pytest against a stub server sees exactly one request for a failed run and none for a clean run.
- [ ] **Write the dashboard.** `dashboard/app.py`, one page, reading only `SERVING_DIR`: the three business questions as one chart or table each, the reconciliation history, and the time of the last successful run with a warning when it is older than twice the schedule interval. Add `streamlit` in a `dashboard` dependency group.
  Done when: the page renders locally from published files with Postgres and the warehouse file both absent.
- [ ] **Write the `Dockerfile`.** One image for every service, built with uv from the lockfile, running as a non-root user.
  Done when: `docker build .` succeeds and `docker run <image> erp --help` prints the subcommands.
- [ ] **Write `compose.prod.yaml`.** Services: `postgres` with no published port; `simulator` running `erp simulate --interval 60 --with-deletes`; `dashboard`; `pipeline` under a `jobs` profile so it starts only on demand. Memory limits: 512 MB, 128 MB, 384 MB, 768 MB. Restart policy `unless-stopped` for the long-running services. A shared volume holds the warehouse file and `SERVING_DIR`.
  Done when: `docker compose -f compose.prod.yaml config` validates and the stack starts on the development machine.
- [ ] **Schedule the pipeline.** `infra/cron/erp-pipeline` runs `docker compose run --rm pipeline erp run` every 30 minutes inside `flock -n`, appending to a log file with rotation configured.
  Done when: starting a second run by hand while one is active exits immediately without starting a container.
- [ ] **Back up Postgres.** A nightly cron entry runs `pg_dump` in the Postgres container and uploads the compressed dump to `s3://<bucket>/backups/`, keeping the last seven. The simulated ERP is not disposable: its ids are referenced by the raw history.
  Done when: a dump restores into an empty database on the development machine.
- [ ] **Route the hostname.** With no existing reverse proxy, add a Caddy service to `compose.prod.yaml` terminating TLS for the dashboard. With one, write the upstream snippet into the runbook.
  Done when: the dashboard answers over HTTPS on its hostname.
- [ ] **Write `infra/deploy.sh` and the deploy workflow.** The script pulls, builds, runs `erp db migrate`, and brings the stack up. A GitHub Actions workflow runs it over SSH after CI passes on `main`, using repository secrets the human sets.
  Done when: the script is idempotent on an already deployed host.
- [ ] **Write `docs/runbook.md`.** First deployment step by step, then one entry per alert: what it means, how to confirm, how to recover. Include re-running a failed window, restoring Postgres from a dump, and rebuilding the warehouse from raw.
  Done when: every alert message `erp run` can send has a matching entry.

## Acceptance

```bash
docker build -t erp-platform .
docker compose -f compose.prod.yaml config
uv run --env-file .env pytest
uv run ruff check . && uv run ruff format --check .
```

On the VPS, after the first deployment:

- three consecutive scheduled runs finish with exit status 0 and `reconciliation_runs` shows only matches
- stopping Postgres makes the next run send one alert, and the run after Postgres returns succeeds without manual steps
- `docker stats` shows every container under its memory limit

## Out of scope

An orchestrator, metrics dashboards, and multi-host deployment are deferred.
