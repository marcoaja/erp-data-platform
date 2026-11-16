-- Two versions of one id overlap when one starts before the other ends. Returns offending pairs.
with intervals as (

    select 'dealer' as dimension, dealer_id as id, valid_from, valid_to from {{ ref('dim_dealer') }}
    union all
    select 'part' as dimension, part_id as id, valid_from, valid_to from {{ ref('dim_part') }}

)

select
    earlier.dimension,
    earlier.id,
    earlier.valid_from as earlier_valid_from,
    later.valid_from as later_valid_from
from intervals as earlier
inner join intervals as later
    on earlier.dimension = later.dimension
    and earlier.id = later.id
    and earlier.valid_from < later.valid_from
    and (earlier.valid_to is null or earlier.valid_to > later.valid_from)
