with source as (

    select * from {{ source('fx', 'fx_rates') }}

),

renamed as (

    select
        cast(date as date) as rate_date,
        base as base_currency,
        quote as currency_code,
        cast(rate as decimal(18, 8)) as rate,
        _run_id,
        _extracted_at
    from source

)

-- The API revises recent rates; the most recently fetched value of a day wins.
select * from renamed
qualify row_number() over (partition by rate_date, currency_code order by _extracted_at desc) = 1
