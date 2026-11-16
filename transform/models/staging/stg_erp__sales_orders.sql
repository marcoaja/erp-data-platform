with source as (

    select * from {{ source('erp', 'sales_orders') }}

),

renamed as (

    select
        id as order_id,
        order_number,
        dealer_id,
        customer_id,
        status,
        currency_code,
        ordered_at,
        shipped_at,
        delivered_at,
        created_at,
        updated_at,
        _run_id,
        _extracted_at
    from source

),

deduplicated as (

    -- Overlapping extracts write the same version more than once; keep the latest copy.
    select * from renamed
    qualify row_number() over (partition by order_id, updated_at order by _extracted_at desc) = 1

)

select
    *,
    row_number() over (partition by order_id order by updated_at desc) = 1 as is_current
from deduplicated
