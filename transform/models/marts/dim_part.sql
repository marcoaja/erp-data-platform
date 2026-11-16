with versions as (

    select * from {{ ref('stg_erp__parts') }}

),

intervals as (

    select
        *,
        -- The first known version covers the row's whole life before it was first changed.
        case
            when row_number() over (partition by part_id order by updated_at) = 1 then created_at
            else updated_at
        end as valid_from,
        lead(updated_at) over (partition by part_id order by updated_at) as valid_to
    from versions

)

select
    {{ dbt_utils.generate_surrogate_key(['part_id', 'valid_from']) }} as part_key,
    part_id,
    part_number,
    part_name,
    machine_model,
    category,
    list_price_jpy,
    is_active,
    valid_from,
    valid_to,
    is_current
from intervals
