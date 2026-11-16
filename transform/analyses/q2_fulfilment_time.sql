-- Q2. How long does order fulfilment take, per dealer and per region?
-- The region is the one the dealer had when the order was placed.
select
    dealers.region,
    dealers.dealer_code,
    count(*) as orders,
    avg(orders.hours_to_ship) as avg_hours_to_ship,
    avg(orders.hours_to_deliver) as avg_hours_to_deliver
from {{ ref('fct_orders') }} as orders
inner join {{ ref('dim_dealer') }} as dealers on orders.dealer_key = dealers.dealer_key
where orders.order_status <> 'cancelled'
group by dealers.region, dealers.dealer_code
order by dealers.region, dealers.dealer_code
