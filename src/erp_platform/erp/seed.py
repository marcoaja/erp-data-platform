import logging
import random
from datetime import datetime, timedelta
from decimal import Decimal

import psycopg
from faker import Faker

from erp_platform.config import Settings
from erp_platform.db import connect
from erp_platform.erp.simulate import REGIONS, unit_price

log = logging.getLogger(__name__)

HISTORY_DAYS = 90
DEALERS_PER_COUNTRY = 10
PART_COUNT = 500
CUSTOMER_COUNT = 2000
ORDER_COUNT = 3000
CANCELLED_SHARE = 0.05

COUNTRIES = {"JP": ("ja_JP", "JPY"), "ID": ("id_ID", "IDR"), "TH": ("th_TH", "THB")}

MACHINE_MODELS = [
    "T-250 Tractor",
    "T-400 Tractor",
    "H-120 Harvester",
    "H-300 Harvester",
    "R-50 Rice Transplanter",
    "R-80 Rice Transplanter",
    "C-30 Cultivator",
    "S-200 Sprayer",
]
PART_NOUNS = {
    "Engine": ["Piston", "Gasket", "Injector", "Cylinder Liner"],
    "Hydraulics": ["Pump", "Hose", "Valve", "Seal Kit"],
    "Filters": ["Oil Filter", "Air Filter", "Fuel Filter", "Cabin Filter"],
    "Transmission": ["Clutch Disc", "Gear", "Shaft", "Bearing"],
    "Electrical": ["Alternator", "Starter", "Relay", "Wiring Harness"],
    "Cutting": ["Blade", "Knife Guard", "Sickle", "Cutter Bar"],
    "Undercarriage": ["Track Pad", "Roller", "Idler", "Sprocket"],
    "Belts and Chains": ["V-Belt", "Drive Chain", "Tensioner", "Pulley"],
}
PART_VARIANTS = ["Standard", "Heavy Duty", "Compact", "Long Life"]


def _is_empty(conn: psycopg.Connection, table: str) -> bool:
    return conn.execute(f"select not exists (select 1 from erp.{table})").fetchone() == (True,)


def _fake(country: str, seed: int) -> Faker:
    fake = Faker(COUNTRIES[country][0])
    fake.seed_instance(seed)
    return fake


def seed_dealers(conn: psycopg.Connection, seed: int, start: datetime) -> int:
    rows = []
    for index, country in enumerate(COUNTRIES):
        fake = _fake(country, seed + index)
        regions = REGIONS[country]
        for n in range(DEALERS_PER_COUNTRY):
            rows.append(
                (
                    f"{country}-{n + 1:03d}",
                    f"{fake.city()} Agri Dealer",
                    country,
                    regions[n % len(regions)],
                    COUNTRIES[country][1],
                    start,
                    start,
                )
            )
    with conn.cursor() as cur:
        cur.executemany(
            "insert into erp.dealers"
            " (dealer_code, name, country_code, region, currency_code, created_at, updated_at)"
            " values (%s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
    return len(rows)


def seed_parts(conn: psycopg.Connection, seed: int, start: datetime) -> int:
    rng = random.Random(f"{seed}:parts")
    categories = list(PART_NOUNS)
    rows = []
    for n in range(PART_COUNT):
        model = MACHINE_MODELS[n % len(MACHINE_MODELS)]
        category = rng.choice(categories)
        name = f"{rng.choice(PART_NOUNS[category])} {rng.choice(PART_VARIANTS)}"
        # Log-uniform between 300 and 180,000 yen: many cheap consumables, few expensive units.
        price = Decimal(str(round(300 * 600 ** rng.random(), 2)))
        rows.append((f"P-{n + 1:04d}", name, model, category, price, start, start))
    with conn.cursor() as cur:
        cur.executemany(
            "insert into erp.parts"
            " (part_number, name, machine_model, category, list_price_jpy, created_at, updated_at)"
            " values (%s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
    return len(rows)


def seed_customers(conn: psycopg.Connection, seed: int, start: datetime) -> int:
    dealers = conn.execute("select id, country_code from erp.dealers order by id").fetchall()
    fakes = {country: _fake(country, seed + 100 + i) for i, country in enumerate(COUNTRIES)}
    rows = []
    for n in range(CUSTOMER_COUNT):
        dealer_id, country = dealers[n % len(dealers)]
        fake = fakes[country]
        rows.append(
            (dealer_id, fake.name(), fake.email(), fake.phone_number(), fake.city(), start, start)
        )
    with conn.cursor() as cur:
        cur.executemany(
            "insert into erp.customers"
            " (dealer_id, name, email, phone, city, created_at, updated_at)"
            " values (%s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
    return len(rows)


def seed_orders(conn: psycopg.Connection, seed: int, now: datetime) -> tuple[int, int]:
    """Insert orders across the history window; status follows how far each has progressed."""
    rng = random.Random(f"{seed}:orders")
    dealers = conn.execute("select id, currency_code from erp.dealers order by id").fetchall()
    customers: dict[int, list[int]] = {}
    for customer_id, dealer_id in conn.execute(
        "select id, dealer_id from erp.customers order by id"
    ):
        customers.setdefault(dealer_id, []).append(customer_id)
    parts = conn.execute("select id, list_price_jpy from erp.parts order by id").fetchall()

    window = timedelta(days=HISTORY_DAYS).total_seconds()
    ordered = sorted(now - timedelta(seconds=rng.uniform(0, window)) for _ in range(ORDER_COUNT))

    orders = []
    lines_by_order: list[list[tuple[int, int, Decimal]]] = []
    for ordered_at in ordered:
        dealer_id, currency = rng.choice(dealers)
        shipped_at: datetime | None = ordered_at + timedelta(hours=rng.uniform(12, 120))
        delivered_at: datetime | None = shipped_at + timedelta(hours=rng.uniform(24, 240))
        if rng.random() < CANCELLED_SHARE:
            status, shipped_at, delivered_at = "cancelled", None, None
            updated_at = min(now, ordered_at + timedelta(hours=rng.uniform(1, 24)))
        elif delivered_at <= now:
            status, updated_at = "delivered", delivered_at
        elif shipped_at <= now:
            status, updated_at, delivered_at = "shipped", shipped_at, None
        else:
            shipped_at = delivered_at = None
            status = "confirmed" if ordered_at + timedelta(days=1) <= now else "placed"
            updated_at = ordered_at + timedelta(hours=1) if status == "confirmed" else ordered_at
        orders.append(
            (
                dealer_id,
                rng.choice(customers[dealer_id]),
                status,
                currency,
                ordered_at,
                shipped_at,
                delivered_at,
                ordered_at,
                updated_at,
            )
        )
        lines_by_order.append(
            [
                (part_id, rng.randint(1, 20), unit_price(rng, list_price, currency))
                for part_id, list_price in rng.sample(parts, k=rng.randint(1, 5))
            ]
        )

    order_ids = []
    with conn.cursor() as cur:
        cur.executemany(
            "insert into erp.sales_orders (dealer_id, customer_id, status, currency_code,"
            " ordered_at, shipped_at, delivered_at, created_at, updated_at)"
            " values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
            orders,
            returning=True,
        )
        while True:
            order_ids.append(cur.fetchone()[0])  # type: ignore[index]
            if not cur.nextset():
                break
        line_rows = [
            (order_id, number, part_id, quantity, price, order[4], order[4])
            for order_id, order, lines in zip(order_ids, orders, lines_by_order, strict=True)
            for number, (part_id, quantity, price) in enumerate(lines, start=1)
        ]
        cur.executemany(
            "insert into erp.order_lines (order_id, line_number, part_id, quantity, unit_price,"
            " created_at, updated_at) values (%s, %s, %s, %s, %s, %s, %s)",
            line_rows,
        )
    return len(orders), len(line_rows)


def seed(settings: Settings, *, seed: int = 42) -> None:
    """Load master data and 90 days of orders; each step is skipped when its table has rows."""
    with connect(settings, autocommit=True) as conn:
        now = conn.execute("select now()").fetchone()[0]  # type: ignore[index]
        start = now - timedelta(days=HISTORY_DAYS)
        steps = [
            ("dealers", lambda: seed_dealers(conn, seed, start)),
            ("parts", lambda: seed_parts(conn, seed, start)),
            ("customers", lambda: seed_customers(conn, seed, start)),
            ("sales_orders", lambda: seed_orders(conn, seed, now)),
        ]
        for table, step in steps:
            with conn.transaction():
                if not _is_empty(conn, table):
                    log.info("seed %s skipped: table already has rows", table)
                    continue
                log.info("seed %s inserted=%s", table, step())
