with source as (

    select * from {{ source('erp', 'order_lines') }}

),

live_keys as (

    -- Every id present in the ERP at the latest extract; a hard delete leaves no other trace.
    select id from {{ source('erp_keys', 'order_lines') }}

),

renamed as (

    select
        id as order_line_id,
        order_id,
        line_number,
        part_id,
        quantity,
        cast(unit_price as decimal(14, 2)) as unit_price,
        created_at,
        updated_at,
        _run_id,
        _extracted_at
    from source

),

deduplicated as (

    -- Overlapping extracts write the same version more than once; keep the latest copy.
    select * from renamed
    qualify
        row_number() over (partition by order_line_id, updated_at order by _extracted_at desc) = 1

)

select
    deduplicated.*,
    row_number() over (
        partition by deduplicated.order_line_id order by deduplicated.updated_at desc
    ) = 1 as is_current,
    live_keys.id is null as is_deleted
from deduplicated
left join live_keys on deduplicated.order_line_id = live_keys.id
