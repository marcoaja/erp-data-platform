with source as (

    select * from {{ source('erp', 'inventory') }}

),

live_keys as (

    -- Every id present in the ERP at the latest extract; a hard delete leaves no other trace.
    select id from {{ source('erp_keys', 'inventory') }}

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
    deduplicated.*,
    row_number() over (
        partition by deduplicated.inventory_id order by deduplicated.updated_at desc
    ) = 1 as is_current,
    live_keys.id is null as is_deleted
from deduplicated
left join live_keys on deduplicated.inventory_id = live_keys.id
