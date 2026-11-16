create table erp.inventory (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    dealer_id bigint not null references erp.dealers (id),
    part_id bigint not null references erp.parts (id),
    quantity_on_hand integer not null check (quantity_on_hand >= 0),
    reorder_point integer not null check (reorder_point >= 0),
    unique (dealer_id, part_id)
);

create index inventory_updated_at_idx on erp.inventory (updated_at);

create trigger inventory_set_updated_at before update on erp.inventory
    for each row execute function erp.set_updated_at();
