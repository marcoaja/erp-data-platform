with orders as (

    select * from {{ ref('stg_erp__sales_orders') }}
    where is_current

),

dealers as (

    select * from {{ ref('dim_dealer') }}

),

customers as (

    select * from {{ ref('dim_customer') }}

)

select
    orders.order_id,
    orders.order_number,
    dealers.dealer_key,
    customers.customer_key,
    cast(orders.ordered_at as date) as order_date,
    orders.status as order_status,
    orders.currency_code,
    orders.ordered_at,
    orders.shipped_at,
    orders.delivered_at,
    cast({{ dbt.datediff('orders.ordered_at', 'orders.shipped_at', 'second') }} / 3600.0 as decimal(12, 2))
        as hours_to_ship,
    cast({{ dbt.datediff('orders.ordered_at', 'orders.delivered_at', 'second') }} / 3600.0 as decimal(12, 2))
        as hours_to_deliver
from orders
left join dealers
    on orders.dealer_id = dealers.dealer_id
    and orders.ordered_at >= dealers.valid_from
    and (dealers.valid_to is null or orders.ordered_at < dealers.valid_to)
left join customers on orders.customer_id = customers.customer_id
