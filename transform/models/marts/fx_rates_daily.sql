with rates as (

    select * from {{ ref('stg_fx__rates') }}

),

days as (

    select date_day from {{ ref('dim_date') }}

),

rate_intervals as (

    -- Each published rate holds until the next published date of the same currency.
    select
        currency_code,
        rate_date,
        rate,
        lead(rate_date) over (partition by currency_code order by rate_date) as next_rate_date
    from rates

),

forward_filled as (

    select
        days.date_day,
        rate_intervals.currency_code,
        rate_intervals.rate,
        rate_intervals.rate_date as source_date
    from rate_intervals
    inner join days
        on
            rate_intervals.rate_date <= days.date_day
            and (
                rate_intervals.next_rate_date is null
                or rate_intervals.next_rate_date > days.date_day
            )
            and days.date_day <= {{ today() }}

),

jpy as (

    select
        date_day,
        'JPY' as currency_code,
        cast(1 as decimal(18, 8)) as rate,
        date_day as source_date
    from days
    where
        date_day >= (select min(rates.rate_date) from rates)
        and date_day <= {{ today() }}

)

select
    date_day,
    currency_code,
    rate,
    source_date
from forward_filled
union all
select
    date_day,
    currency_code,
    rate,
    source_date
from jpy
