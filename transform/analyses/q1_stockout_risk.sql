-- Q1. Which dealers risk running out of a part within seven days?
select
    dealer_code,
    dealer_name,
    region,
    part_number,
    part_name,
    quantity_on_hand,
    units_sold_28d,
    days_of_cover
from {{ ref('rpt_stockout_risk') }}
where is_at_risk
order by days_of_cover, dealer_code, part_number
