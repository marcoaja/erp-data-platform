# Stage 7: Snowflake

**Goal.** The same dbt project builds the same marts on Snowflake from the same raw files in R2, with role-based access and masked customer data.

**Depends on.** Stage 3 at minimum, and an R2 bucket holding the raw layer. Later stages add models; whatever exists is migrated.

**Human prerequisites.**

- A Snowflake trial on **Enterprise** edition, created when this stage starts so the 30 days are not spent waiting. Masking policies need Enterprise.
- The human runs the bootstrap script as `ACCOUNTADMIN` and generates the key pair for the service user; write both steps into `infra/snowflake/README.md` first.
- The human records the demo video and screenshots at the end.

The trial has a fixed credit budget. Use one X-Small warehouse with a 60-second auto-suspend, and stop to report if the resource monitor triggers.

The stage URL format and its limits are under "Verified external facts" in [ARCHITECTURE.md](ARCHITECTURE.md). Check the current Snowflake documentation for every statement you write here.

## Tasks

- [ ] **Write `infra/snowflake/01_bootstrap.sql`.** Idempotent. Creates: warehouse `ERP_WH` (X-Small, auto-suspend 60, auto-resume); a resource monitor capping credits and suspending the warehouse at the cap; database `ERP_DWH` with schemas `RAW`, `STAGING`, `MARTS`; the roles below; a service user of type `SERVICE` with key-pair authentication and default role `ERP_TRANSFORMER`.
  Done when: running the script twice produces no error and no change.

  | Role | Can |
  |---|---|
  | `ERP_LOADER` | use the stage, write `RAW` |
  | `ERP_TRANSFORMER` | read `RAW`, own `STAGING` and `MARTS` |
  | `ERP_ANALYST` | read `MARTS`, sees customer data masked |
  | `ERP_PII_ANALYST` | read `MARTS`, sees customer data in clear |

- [ ] **Put the raw layer in R2 when stage 6 has not run.** Add target `r2` to `profiles.yml` with the storage secret from the `S3_*` variables, set `RAW_URI=s3://<bucket>/raw`, and run `erp run` once.
  Done when: the bucket holds the raw files and `dbt build --target r2` passes.
- [ ] **Write `02_stage.sql`.** A Parquet file format and an external stage on the bucket's `raw/` prefix using the `s3compat://` URL and the R2 endpoint. Credentials are passed as session variables, never written into the file.
  Done when: `list @<stage>` returns the raw files.
- [ ] **Write `erp snowflake-load`.** For each raw table: create the `RAW` table from the files' inferred schema when it is missing, with schema evolution enabled; then `copy into` matching columns by name. Append-only tables rely on Snowflake's load history to skip files already loaded. The key-snapshot tables are replaced on every load. Add `snowflake-connector-python` in a `snowflake` dependency group.
  Done when: two consecutive loads leave identical row counts in every `RAW` table.
- [ ] **Add the `snowflake` target** to `profiles.yml` with key-pair authentication, and `dbt-snowflake` to the `snowflake` dependency group.
  Done when: `dbt debug --target snowflake` passes.
- [ ] **Make the models portable.** Run `dbt build --target snowflake` and fix each failure by replacing dialect-specific SQL with a dbt cross-database macro, keeping one version of every model. Record each change in `docs/decisions.md`.
  Done when: `dbt build` passes on both `local` and `snowflake` from the same commit.
- [ ] **Mask customer data.** Masking policies for `name`, `email`, and `phone` that return the clear value to `ERP_PII_ANALYST` and `ERP_TRANSFORMER` and a masked value to every other role. Attach them to `dim_customer` with a dbt post-hook that runs on the Snowflake target only, because a rebuild replaces the table and drops the attachment.
  Done when: the same query returns masked values as `ERP_ANALYST` and clear values as `ERP_PII_ANALYST`, after a fresh `dbt build`.
- [ ] **Prove parity.** A script compares row counts and the key totals of every mart between DuckDB and Snowflake built from the same raw files.
  Done when: its output shows no difference and is saved to `docs/snowflake-parity.md`.
- [ ] **Write `docs/snowflake.md`.** What was built, the role diagram, the masking demonstration, the parity result, credits consumed, and the list of evidence the human should capture before the trial ends.
  Done when: the human can record the demo by following the document.

## Acceptance

```bash
uv run --env-file .env erp snowflake-load
uv run --env-file .env dbt build --project-dir transform --profiles-dir transform --target snowflake
uv run --env-file .env dbt build --project-dir transform --profiles-dir transform --target local
uv run --env-file .env pytest
```

In Snowflake: `select count(*) from ERP_DWH.MARTS.RECONCILIATION_RUNS where not is_match` returns 0 when stage 5 is done, and the masking check above holds.

## Out of scope

The dashboard keeps reading DuckDB output, because the trial account will end. Snowpipe, external tables, and Iceberg are deferred.
