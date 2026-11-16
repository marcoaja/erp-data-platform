with source as (

    select * from {{ source('erp', 'inventory') }}

),

renamed as (

    select
        id as inventory_id,
        dealer_id,
        part_id,
        quantity_on_hand,
        reorder_point,
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
        row_number() over (partition by inventory_id, updated_at order by _extracted_at desc) = 1

)

select
    *,
    row_number() over (partition by inventory_id order by updated_at desc) = 1 as is_current
from deduplicated
