# Stage 4: Business marts

**Goal.** The warehouse answers the three business questions, using real exchange rates and a new inventory source.

**Depends on.** Stage 3.

**Human prerequisites.** None. The exchange-rate API needs no key.

Model grains are specified under "Marts" in [ARCHITECTURE.md](ARCHITECTURE.md); the API contract is under "Verified external facts".

## Tasks

- [x] **Add inventory to the ERP.** A new migration creates `erp.inventory` following the table conventions. `erp seed` gains a step that stocks every dealer with a subset of parts, safe to run on an already seeded database. The simulator decrements stock when an order ships and replenishes a part that falls below its reorder point after a delay of several ticks, so some parts do run low.
  Done when: a pytest runs 50 ticks and finds stock decreased for shipped parts, never negative, and at least one replenishment.
- [x] **Extract inventory.** Add the table to the extract list.
  Done when: the first extract after the migration loads the table in full, with no change to the other tables' watermarks.
- [x] **Write `erp fx`.** Fetch JPY-based daily rates for IDR and THB into `<RAW_URI>/fx_rates/extract_date=…/<run_id>.parquet`. The first run starts at the earliest `ordered_at`; later runs start seven days before the last stored date, because published rates get revised. Use a request timeout and one retry. Add `httpx` as a dependency.
  Done when: a pytest against a stubbed HTTP response writes the expected rows, and a second run on the same day adds no new dates.
- [x] **Make an API failure soft.** `erp run` logs a warning and continues when `erp fx` fails.
  Done when: a pytest with the API unreachable sees `erp run` finish with exit status 0 and a warning in the log.
- [x] **Write `stg_fx__rates` and `fx_rates_daily`.** Staging keeps the latest fetched value per date and currency. The daily model has a row for every calendar day, filled forward from the last published rate, plus a JPY row with rate 1.
  Done when: a dbt unit test with a Friday and a Monday rate expects Saturday and Sunday to carry Friday's value.
- [x] **Add `amount_jpy` to `fct_sales`:** `amount_local / rate` on the order date.
  Done when: `not_null` on `amount_jpy` passes and a unit test checks one IDR line by hand.
- [x] **Write `stg_erp__inventory` and `fct_inventory_daily`.**
  Done when: `unique` on (`dealer_id`, `part_id`, `date_key`) passes.
- [x] **Write `rpt_stockout_risk`.** Days of cover is current stock divided by average daily quantity sold over the trailing 28 days. A pair with no sales in that window has null days of cover and is not at risk.
  Done when: a unit test covers a part at risk, a part with ample stock, and a part with no sales.
- [x] **Answer the questions.** Three files in `transform/analyses/`, one per business question, each a single query over marts.
  Done when: each compiled query runs against the warehouse and returns rows.
- [x] **Update the README** with the three questions and the mart that answers each.
  Done when: the README names a model for every question.

## Acceptance

```bash
uv run --env-file .env erp db migrate
uv run --env-file .env erp seed
uv run --env-file .env erp simulate --ticks 50 --seed 7
uv run --env-file .env erp run
uv run sqlfluff lint transform/models
uv run --env-file .env pytest
```

After these commands, `select count(*) from marts.rpt_stockout_risk where is_at_risk` returns a number greater than zero.

## Out of scope

Reconciliation, delete handling, and schema-change handling are stage 5. A second real data source is deferred.
