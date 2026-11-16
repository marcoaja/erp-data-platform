with source as (

    select * from {{ source('erp', 'order_lines') }}

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
    qualify row_number() over (partition by order_line_id, updated_at order by _extracted_at desc) = 1

)

select
    *,
    row_number() over (partition by order_line_id order by updated_at desc) = 1 as is_current
from deduplicated
