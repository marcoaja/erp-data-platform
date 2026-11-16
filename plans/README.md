# Plans

Each stage file is a self-contained brief for one agent run. Stages run in order; a stage starts only when the stages it depends on are `done`.

## Stages

| Stage | File | Depends on | Status |
|---|---|---|---|
| 0 | [stage-0-foundation.md](stage-0-foundation.md) | none | done |
| 1 | [stage-1-erp-source.md](stage-1-erp-source.md) | 0 | done |
| 2 | [stage-2-ingestion.md](stage-2-ingestion.md) | 1 | done |
| 3 | [stage-3-warehouse.md](stage-3-warehouse.md) | 2 | done |
| 4 | [stage-4-business-marts.md](stage-4-business-marts.md) | 3 | todo |
| 5 | [stage-5-reliability.md](stage-5-reliability.md) | 4 | todo |
| 6 | [stage-6-deploy.md](stage-6-deploy.md) | 5 | todo |
| 7 | [stage-7-snowflake.md](stage-7-snowflake.md) | 3, an R2 bucket | todo |
| 8 | [stage-8-documentation.md](stage-8-documentation.md) | every stage that will ship | todo |

Short path when time is tight: 0 → 1 → 2 → 3 → 7 → 8.

## Execution protocol

1. Read `CLAUDE.md`, [ARCHITECTURE.md](ARCHITECTURE.md), and your stage file in full.
2. Check the stage's **Depends on** rows are `done` in the table above and every item under **Human prerequisites** is present. If one is missing, stop and report exactly what is needed.
3. Work the tasks in order. A task is done when its **Done when** check passes; tick its checkbox then.
4. Run every command under **Acceptance**. The stage is done when all of them pass on a clean checkout.
5. Append the trade-offs you made to `docs/decisions.md`. If you changed a contract, update `ARCHITECTURE.md` in the same commit.
6. Set the stage's status to `done` in the table above and commit.
7. Report: what was built, the acceptance output, and every deviation from the plan with its reason.

One stage per agent run. Stop at the stage boundary.

## Human prerequisites at a glance

| Stage | The human provides |
|---|---|
| 0–5 | Docker Desktop, `uv`, Git on the development machine |
| 6 | VPS SSH access, a hostname for the dashboard, a Cloudflare R2 bucket with an API token, a Discord webhook URL |
| 7 | A Snowflake trial account on **Enterprise** edition, created only when this stage starts |
