-- Every current order line yields exactly one fct_sales row, and the dealer and part versions
-- on that row were in force when the order was placed. Returns offending order lines.
with expected as (

    select order_line_id from {{ ref('stg_erp__order_lines') }} where is_current

),

resolved as (

    select
        sales.order_line_id,
        count(*) as fact_rows,
        count(dealers.dealer_key) as dealer_versions,
        count(parts.part_key) as part_versions
    from {{ ref('fct_sales') }} as sales
    inner join {{ ref('fct_orders') }} as orders on sales.order_id = orders.order_id
    left join {{ ref('dim_dealer') }} as dealers
        on sales.dealer_key = dealers.dealer_key
        and orders.ordered_at >= dealers.valid_from
        and (dealers.valid_to is null or orders.ordered_at < dealers.valid_to)
    left join {{ ref('dim_part') }} as parts
        on sales.part_key = parts.part_key
        and orders.ordered_at >= parts.valid_from
        and (parts.valid_to is null or orders.ordered_at < parts.valid_to)
    group by sales.order_line_id

)

select expected.order_line_id
from expected
left join resolved on expected.order_line_id = resolved.order_line_id
where resolved.fact_rows is distinct from 1
    or resolved.dealer_versions <> 1
    or resolved.part_versions <> 1
