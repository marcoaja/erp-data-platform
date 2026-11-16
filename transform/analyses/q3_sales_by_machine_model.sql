-- Q3. What are parts sales per machine model, in one currency (JPY)?
select
    parts.machine_model,
    count(*) as order_lines,
    sum(sales.quantity) as units_sold,
    sum(sales.amount_jpy) as sales_jpy
from {{ ref('fct_sales') }} as sales
inner join {{ ref('dim_part') }} as parts on sales.part_key = parts.part_key
where sales.order_status <> 'cancelled'
group by parts.machine_model
order by sales_jpy desc
