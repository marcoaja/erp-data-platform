-- The latest extract's source totals must equal the warehouse totals. Returns the mismatches.
select
    run_id,
    table_name,
    metric,
    source_value,
    warehouse_value,
    difference
from {{ ref('reconciliation_runs') }}
where
    not is_match
    and run_id = (select max(run_id) from {{ ref('reconciliation_runs') }})
