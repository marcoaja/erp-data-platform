with source as (

    select * from {{ source('erp', 'parts') }}

),

live_keys as (

    -- Every id present in the ERP at the latest extract; a hard delete leaves no other trace.
    select id from {{ source('erp_keys', 'parts') }}

),

renamed as (

    select
        id as part_id,
        part_number,
        name as part_name,
        machine_model,
        category,
        cast(list_price_jpy as decimal(12, 2)) as list_price_jpy,
        is_active,
        created_at,
        updated_at,
        _run_id,
        _extracted_at
    from source

),

deduplicated as (

    -- Overlapping extracts write the same version more than once; keep the latest copy.
    select * from renamed
    qualify row_number() over (partition by part_id, updated_at order by _extracted_at desc) = 1

)

select
    deduplicated.*,
    row_number() over (
        partition by deduplicated.part_id order by deduplicated.updated_at desc
    ) = 1 as is_current,
    live_keys.id is null as is_deleted
from deduplicated
left join live_keys on deduplicated.part_id = live_keys.id
