with versions as (

    select * from {{ ref('stg_erp__dealers') }}

),

intervals as (

    select
        *,
        -- The first known version covers the row's whole life before it was first changed.
        case
            when row_number() over (partition by dealer_id order by updated_at) = 1 then created_at
            else updated_at
        end as valid_from,
        lead(updated_at) over (partition by dealer_id order by updated_at) as valid_to
    from versions

)

select
    {{ dbt_utils.generate_surrogate_key(['dealer_id', 'valid_from']) }} as dealer_key,
    dealer_id,
    dealer_code,
    dealer_name,
    country_code,
    region,
    currency_code,
    valid_from,
    valid_to,
    is_current
from intervals
