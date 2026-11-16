# Stage 8: Documentation

**Goal.** A reviewer with five minutes understands what the project does, why its design choices were made, and can run it.

**Depends on.** Every stage that will ship.

**Human prerequisites.** The public dashboard URL, and the demo video and screenshots from stage 7 if that stage ran.

Write for a hiring engineer skimming the repository. Lead each document with its conclusion. State limitations plainly; a reviewer trusts a project that names its own gaps.

## Tasks

- [ ] **Rewrite `README.md`.** In this order: one-paragraph summary; link to the live dashboard; the architecture diagram; the three business questions with a screenshot each; "What this project demonstrates" as a short list linking to the incident write-ups; the tech stack with one reason per choice; quickstart; known limitations, starting with the synthetic data.
  Done when: every command in the quickstart works on a clean clone, and the README fits on about two screens before the quickstart.
- [ ] **Draw the architecture diagram** as a Mermaid flowchart in the README, so it renders on GitHub and stays diffable.
  Done when: it shows every component and data store that exists in the repository, and nothing that does not.
- [ ] **Draw two entity diagrams** as Mermaid `erDiagram` blocks in `docs/data-model.md`: the ERP tables, and the star schema with each model's grain.
  Done when: every table and mart appears with its keys and relationships.
- [ ] **Edit `docs/decisions.md`** into its final form: one entry per decision with the alternatives and the condition that would change it, and the "Deferred" list with the reason each item waited.
  Done when: every row of the trade-off table in `plans/ARCHITECTURE.md` has a matching entry.
- [ ] **Review `docs/runbook.md` and `docs/incidents/`** against the code as it now is.
  Done when: every command and file path in them exists.
- [ ] **Review the code comments** across the repository against the rule in `CLAUDE.md`.
  Done when: every remaining comment states a reason the code cannot express.
- [ ] **Add a licence and repository metadata.** An MIT `LICENSE`, and a suggested repository description and topics listed in the final report for the human to set.
  Done when: `LICENSE` exists.

## Acceptance

In a fresh clone of the repository, in a temporary directory:

```bash
cp .env.example .env
docker compose up -d --wait postgres
uv sync
uv run --env-file .env erp db migrate && uv run --env-file .env erp seed
uv run --env-file .env erp simulate --ticks 20 --seed 7
uv run --env-file .env erp run
```

Every link in `README.md` and `docs/` resolves.

## Out of scope

Hosting dbt docs, a blog post, and a Japanese summary are not part of this project.
