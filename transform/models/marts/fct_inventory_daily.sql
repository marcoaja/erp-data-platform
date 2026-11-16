with versions as (

    select * from {{ ref('stg_erp__inventory') }}

),

last_version_per_day as (

    select * from versions
    qualify
        row_number() over (
            partition by inventory_id, cast(updated_at as date) order by updated_at desc
        ) = 1

),

intervals as (

    select
        *,
        -- The first known version covers the row's life before it was first changed.
        case
            when row_number() over (partition by inventory_id order by updated_at) = 1
                then cast(created_at as date)
            else cast(updated_at as date)
        end as valid_from_date,
        lead(cast(updated_at as date)) over (
            partition by inventory_id order by updated_at
        ) as valid_to_date
    from last_version_per_day

),

days as (

    select date_day from {{ ref('dim_date') }}

)

select
    intervals.dealer_id,
    intervals.part_id,
    days.date_day as date_key,
    intervals.quantity_on_hand,
    intervals.reorder_point
from intervals
inner join days
    on
        intervals.valid_from_date <= days.date_day
        and (intervals.valid_to_date is null or intervals.valid_to_date > days.date_day)
        and days.date_day <= {{ today() }}
