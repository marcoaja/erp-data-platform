{{
    config(
        materialized='incremental',
        unique_key=['run_id', 'table_name', 'metric'],
        incremental_strategy='delete+insert',
        full_refresh=false
    )
}}

with totals as (

    select * from {{ source('erp', 'control_totals') }}

),

latest_run as (

    select max(run_id) as run_id from totals

),

source_side as (

    select
        totals.run_id,
        totals.table_name,
        totals.metric,
        totals.value as source_value
    from totals
    inner join latest_run on totals.run_id = latest_run.run_id

),

-- The same expressions as CONTROL_METRICS in ingestion/extract.py, over the current rows.
warehouse_side as (

    -- noqa: disable=LT02
    -- sqlfluff mis-indents the first block that a Jinja loop renders.
    {% for table in ['dealers', 'customers', 'parts', 'sales_orders', 'order_lines', 'inventory'] %}
    select
        '{{ table }}' as table_name,
        'row_count' as metric,
        cast(count(*) as decimal(38, 2)) as warehouse_value
    from {{ ref('stg_erp__' ~ table) }}
    where is_current
    union all
    {% endfor %}
    -- noqa: enable=LT02
    select
        'order_lines' as table_name,
        'sum_quantity' as metric,
        cast(coalesce(sum(quantity), 0) as decimal(38, 2)) as warehouse_value
    from {{ ref('stg_erp__order_lines') }}
    where is_current
    union all
    select
        'order_lines' as table_name,
        'sum_amount_local' as metric,
        cast(coalesce(sum(quantity * unit_price), 0) as decimal(38, 2)) as warehouse_value
    from {{ ref('stg_erp__order_lines') }}
    where is_current
    union all
    select
        'inventory' as table_name,
        'sum_quantity_on_hand' as metric,
        cast(coalesce(sum(quantity_on_hand), 0) as decimal(38, 2)) as warehouse_value
    from {{ ref('stg_erp__inventory') }}
    where is_current

)

select
    source_side.run_id,
    source_side.table_name,
    source_side.metric,
    source_side.source_value,
    warehouse_side.warehouse_value,
    coalesce(warehouse_side.warehouse_value, 0) - source_side.source_value as difference,
    coalesce(warehouse_side.warehouse_value = source_side.source_value, false) as is_match
from source_side
left join warehouse_side
    on
        source_side.table_name = warehouse_side.table_name
        and source_side.metric = warehouse_side.metric
