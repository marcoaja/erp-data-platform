create schema if not exists erp;

create function erp.set_updated_at() returns trigger
language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create sequence erp.order_number_seq;

create table erp.dealers (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    dealer_code text not null unique,
    name text not null,
    country_code text not null check (country_code in ('JP', 'ID', 'TH')),
    region text not null,
    currency_code text not null check (currency_code in ('JPY', 'IDR', 'THB'))
);

create table erp.customers (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    dealer_id bigint not null references erp.dealers (id),
    name text not null,
    email text,
    phone text,
    city text
);

create table erp.parts (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    part_number text not null unique,
    name text not null,
    machine_model text not null,
    category text not null,
    list_price_jpy numeric(12, 2) not null check (list_price_jpy >= 0),
    is_active boolean not null default true
);

create table erp.sales_orders (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    order_number text not null unique
        default 'SO-' || lpad(nextval('erp.order_number_seq')::text, 7, '0'),
    dealer_id bigint not null references erp.dealers (id),
    customer_id bigint not null references erp.customers (id),
    status text not null
        check (status in ('placed', 'confirmed', 'shipped', 'delivered', 'cancelled')),
    currency_code text not null check (currency_code in ('JPY', 'IDR', 'THB')),
    ordered_at timestamptz not null default now(),
    shipped_at timestamptz,
    delivered_at timestamptz,
    check (shipped_at is null or shipped_at >= ordered_at),
    check (delivered_at is null or (shipped_at is not null and delivered_at >= shipped_at))
);

create table erp.order_lines (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    order_id bigint not null references erp.sales_orders (id),
    line_number integer not null,
    part_id bigint not null references erp.parts (id),
    quantity integer not null check (quantity > 0),
    unit_price numeric(14, 2) not null check (unit_price >= 0),
    unique (order_id, line_number)
);

create index dealers_updated_at_idx on erp.dealers (updated_at);
create index customers_updated_at_idx on erp.customers (updated_at);
create index parts_updated_at_idx on erp.parts (updated_at);
create index sales_orders_updated_at_idx on erp.sales_orders (updated_at);
create index order_lines_updated_at_idx on erp.order_lines (updated_at);

create trigger dealers_set_updated_at before update on erp.dealers
    for each row execute function erp.set_updated_at();
create trigger customers_set_updated_at before update on erp.customers
    for each row execute function erp.set_updated_at();
create trigger parts_set_updated_at before update on erp.parts
    for each row execute function erp.set_updated_at();
create trigger sales_orders_set_updated_at before update on erp.sales_orders
    for each row execute function erp.set_updated_at();
create trigger order_lines_set_updated_at before update on erp.order_lines
    for each row execute function erp.set_updated_at();
