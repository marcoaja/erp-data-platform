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
        -- A deleted row's last interval ends when its last version was last extracted, the
        -- latest moment the row is known to have been alive.
        coalesce(
            lead(updated_at) over (partition by part_id order by updated_at),
            case when is_deleted then _extracted_at end
        ) as valid_to
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
    is_current and not is_deleted as is_current
from intervals
