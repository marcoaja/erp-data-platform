with customers as (

    select * from {{ ref('stg_erp__customers') }}
    where is_current and not is_deleted

)

select
    {{ dbt_utils.generate_surrogate_key(['customer_id']) }} as customer_key,
    customer_id,
    dealer_id,
    customer_name,
    email,
    phone,
    city
from customers
