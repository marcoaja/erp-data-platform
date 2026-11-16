with lines as (

    select * from {{ ref('stg_erp__order_lines') }}
    where is_current

),

orders as (

    select * from {{ ref('stg_erp__sales_orders') }}
    where is_current

),

dealers as (

    select * from {{ ref('dim_dealer') }}

),

parts as (

    select * from {{ ref('dim_part') }}

),

customers as (

    select * from {{ ref('dim_customer') }}

)

select
    lines.order_line_id,
    lines.order_id,
    orders.order_number,
    lines.line_number,
    dealers.dealer_key,
    parts.part_key,
    customers.customer_key,
    cast(orders.ordered_at as date) as order_date,
    orders.status as order_status,
    orders.currency_code,
    lines.quantity,
    lines.unit_price,
    lines.quantity * lines.unit_price as amount_local,
    parts.list_price_jpy
from lines
inner join orders on lines.order_id = orders.order_id
left join dealers
    on orders.dealer_id = dealers.dealer_id
    and orders.ordered_at >= dealers.valid_from
    and (dealers.valid_to is null or orders.ordered_at < dealers.valid_to)
left join parts
    on lines.part_id = parts.part_id
    and orders.ordered_at >= parts.valid_from
    and (parts.valid_to is null or orders.ordered_at < parts.valid_to)
left join customers on orders.customer_id = customers.customer_id
