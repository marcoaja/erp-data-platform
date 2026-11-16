with source as (

    select * from {{ source('erp', 'dealers') }}

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
    *,
    row_number() over (partition by dealer_id order by updated_at desc) = 1 as is_current
from deduplicated
