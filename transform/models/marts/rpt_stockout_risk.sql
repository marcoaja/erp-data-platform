with stock as (

    select * from {{ ref('fct_inventory_daily') }}
    where date_key = {{ today() }}

),

sales as (

    select * from {{ ref('fct_sales') }}
    where
        order_status <> 'cancelled'
        and order_date > {{ dbt.dateadd('day', -28, today()) }}
        and order_date <= {{ today() }}

),

dealers as (

    select * from {{ ref('dim_dealer') }}

),

parts as (

    select * from {{ ref('dim_part') }}

),

sold as (

    -- The facts point at dimension versions; the report is keyed by the stable ids.
    select
        dealers.dealer_id,
        parts.part_id,
        sum(sales.quantity) as units_sold_28d
    from sales
    inner join dealers on sales.dealer_key = dealers.dealer_key
    inner join parts on sales.part_key = parts.part_key
    group by dealers.dealer_id, parts.part_id

),

cover as (

    select
        stock.dealer_id,
        stock.part_id,
        stock.quantity_on_hand,
        stock.reorder_point,
        coalesce(sold.units_sold_28d, 0) as units_sold_28d,
        case
            when sold.units_sold_28d > 0
                then stock.quantity_on_hand / (sold.units_sold_28d / 28.0)
        end as days_of_cover
    from stock
    left join sold on stock.dealer_id = sold.dealer_id and stock.part_id = sold.part_id

)

select
    cover.dealer_id,
    dealers.dealer_code,
    dealers.dealer_name,
    dealers.region,
    cover.part_id,
    parts.part_number,
    parts.part_name,
    parts.machine_model,
    cover.quantity_on_hand,
    cover.reorder_point,
    cover.units_sold_28d,
    cast(cover.days_of_cover as decimal(12, 2)) as days_of_cover,
    coalesce(cover.days_of_cover < 7, false) as is_at_risk
from cover
inner join dealers on cover.dealer_id = dealers.dealer_id and dealers.is_current
inner join parts on cover.part_id = parts.part_id and parts.is_current
