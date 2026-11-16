-- The newest extract's source totals must equal the warehouse totals. Returns the mismatches, and
-- one row when that extract has no comparison at all. The run is taken from the control totals,
-- not from the history table: a later run id in the history must not hide the current run.
with newest as (

    select max(run_id) as run_id from {{ source('erp', 'control_totals') }}

),

compared as (

    select reconciliation_runs.*
    from {{ ref('reconciliation_runs') }} as reconciliation_runs
    inner join newest on reconciliation_runs.run_id = newest.run_id

)

select
    run_id,
    table_name,
    metric,
    source_value,
    warehouse_value,
    difference
from compared
where not is_match

union all

select
    newest.run_id,
    cast(null as varchar) as table_name,
    'no comparison rows for this run' as metric,
    cast(null as decimal(38, 2)) as source_value,
    cast(null as decimal(38, 2)) as warehouse_value,
    cast(null as decimal(38, 2)) as difference
from newest
where not exists (select 1 from compared)
