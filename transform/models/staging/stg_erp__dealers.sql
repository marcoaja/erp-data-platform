with source as (

    select * from {{ source('erp', 'dealers') }}

),

live_keys as (

    -- Every id present in the ERP at the latest extract; a hard delete leaves no other trace.
    select id from {{ source('erp_keys', 'dealers') }}

),

renamed as (

    select
        id as dealer_id,
        dealer_code,
        name as dealer_name,
        country_code,
        region,
        currency_code,
        created_at,
        updated_at,
        _run_id,
        _extracted_at
    from source

),

deduplicated as (

    -- Overlapping extracts write the same version more than once; keep the latest copy.
    select * from renamed
    qualify row_number() over (partition by dealer_id, updated_at order by _extracted_at desc) = 1

)

select
    deduplicated.*,
    row_number() over (
        partition by deduplicated.dealer_id order by deduplicated.updated_at desc
    ) = 1 as is_current,
    live_keys.id is null as is_deleted
from deduplicated
left join live_keys on deduplicated.dealer_id = live_keys.id
