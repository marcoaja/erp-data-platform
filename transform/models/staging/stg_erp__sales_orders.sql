with source as (

    select * from {{ source('erp', 'sales_orders') }}

),

live_keys as (

    -- Every id present in the ERP at the latest extract; a hard delete leaves no other trace.
    select id from {{ source('erp_keys', 'sales_orders') }}

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
        -- Null on orders that predate the column (see docs/incidents/schema-evolution.md).
        sales_channel,
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
    deduplicated.*,
    row_number() over (
        partition by deduplicated.order_id order by deduplicated.updated_at desc
    ) = 1 as is_current,
    live_keys.id is null as is_deleted
from deduplicated
left join live_keys on deduplicated.order_id = live_keys.id
