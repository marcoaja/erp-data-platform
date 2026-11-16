with spine as (

    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2020-01-01' as date)",
        end_date="cast('2031-01-01' as date)"
    ) }}

)

select
    cast(date_day as date) as date_day,
    extract(year from date_day) as year_number,
    extract(month from date_day) as month_number,
    extract(day from date_day) as day_of_month,
    cast({{ dbt.date_trunc('month', 'date_day') }} as date) as month_start
from spine
