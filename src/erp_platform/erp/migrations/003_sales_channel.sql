-- Nullable on purpose: orders that predate the column keep null, and no existing writer breaks.
alter table erp.sales_orders
    add column sales_channel text
        check (sales_channel in ('dealer_portal', 'phone', 'email'));
