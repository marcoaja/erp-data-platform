import logging
import random
import signal
import threading
from dataclasses import dataclass, field
from decimal import Decimal

import psycopg

from erp_platform.config import Settings
from erp_platform.db import connect

log = logging.getLogger(__name__)

# Units of each currency per one JPY. Fixed so order prices stay reproducible; `erp fx` fetches
# real rates for reporting, and these constants only generate the source data.
FX_PER_JPY = {"JPY": Decimal("1"), "IDR": Decimal("105"), "THB": Decimal("0.23")}
MAX_DISCOUNT = 0.15

REGIONS = {
    "JP": ["Kanto", "Kansai", "Hokkaido", "Kyushu", "Chubu"],
    "ID": ["Java", "Sumatra", "Kalimantan", "Sulawesi"],
    "TH": ["Central", "North", "Northeast", "South"],
}

# Probability that an order in each status moves one step during a tick.
ADVANCE_PROBABILITY = {"placed": 0.6, "confirmed": 0.4, "shipped": 0.3}
NEXT_STATUS = {"placed": "confirmed", "confirmed": "shipped", "shipped": "delivered"}
CANCEL_PROBABILITY = 0.05
MOVE_DEALER_PROBABILITY = 0.15

# A part below its reorder point arrives again after this many ticks.
REPLENISH_DELAY_TICKS = (3, 6)
REPLENISH_TARGET_MULTIPLE = (3, 6)

CENT = Decimal("0.01")


@dataclass
class SimulationState:
    """Replenishment orders in flight. Derived from stock levels, so a restart loses nothing."""

    tick_number: int = 0
    due_tick: dict[int, int] = field(default_factory=dict)


def unit_price(rng: random.Random, list_price_jpy: Decimal, currency: str) -> Decimal:
    """List price in the order currency, less a random discount of up to 15%."""
    discount = Decimal(str(round(rng.uniform(0, MAX_DISCOUNT), 4)))
    return (list_price_jpy * FX_PER_JPY[currency] * (1 - discount)).quantize(CENT)


def create_orders(conn: psycopg.Connection, rng: random.Random) -> int:
    with conn.transaction():
        dealers = conn.execute("select id, currency_code from erp.dealers order by id").fetchall()
        customers: dict[int, list[int]] = {}
        for customer_id, dealer_id in conn.execute(
            "select id, dealer_id from erp.customers order by id"
        ):
            customers.setdefault(dealer_id, []).append(customer_id)
        parts = conn.execute(
            "select id, list_price_jpy from erp.parts where is_active order by id"
        ).fetchall()
        count = rng.randint(5, 12)
        for _ in range(count):
            dealer_id, currency = rng.choice(dealers)
            (order_id,) = conn.execute(
                "insert into erp.sales_orders (dealer_id, customer_id, status, currency_code)"
                " values (%s, %s, 'placed', %s) returning id",
                (dealer_id, rng.choice(customers[dealer_id]), currency),
            ).fetchone()
            lines = [
                (
                    order_id,
                    number,
                    part_id,
                    rng.randint(1, 20),
                    unit_price(rng, list_price, currency),
                )
                for number, (part_id, list_price) in enumerate(
                    rng.sample(parts, k=rng.randint(1, 5)), start=1
                )
            ]
            with conn.cursor() as cur:
                cur.executemany(
                    "insert into erp.order_lines"
                    " (order_id, line_number, part_id, quantity, unit_price)"
                    " values (%s, %s, %s, %s, %s)",
                    lines,
                )
    return count


def cancel_placed_orders(conn: psycopg.Connection, rng: random.Random) -> int:
    with conn.transaction():
        placed = [
            r[0]
            for r in conn.execute(
                "select id from erp.sales_orders where status = 'placed' order by id"
            )
        ]
        cancelled = [i for i in placed if rng.random() < CANCEL_PROBABILITY]
        conn.execute(
            "update erp.sales_orders set status = 'cancelled' where id = any(%s::bigint[])",
            (cancelled,),
        )
    return len(cancelled)


def advance_orders(conn: psycopg.Connection, rng: random.Random) -> int:
    stamp = {"shipped": ", shipped_at = now()", "delivered": ", delivered_at = now()"}
    advanced = 0
    with conn.transaction():
        open_orders = conn.execute(
            "select id, status from erp.sales_orders"
            " where status in ('placed', 'confirmed', 'shipped') order by id"
        ).fetchall()
        for status, target in NEXT_STATUS.items():
            ids = [
                i
                for i, s in open_orders
                if s == status and rng.random() < ADVANCE_PROBABILITY[status]
            ]
            # The stamp fragments come from the constant above, never from input.
            conn.execute(
                f"update erp.sales_orders set status = %s{stamp.get(target, '')}"
                " where id = any(%s::bigint[])",
                (target, ids),
            )
            if target == "shipped":
                ship_stock(conn, ids)
            advanced += len(ids)
    return advanced


def ship_stock(conn: psycopg.Connection, order_ids: list[int]) -> None:
    """Take shipped quantities out of the dealer's stock, never below zero."""
    conn.execute(
        "update erp.inventory i set quantity_on_hand = greatest(0, i.quantity_on_hand - s.qty)"
        " from (select o.dealer_id, l.part_id, sum(l.quantity) as qty"
        "       from erp.order_lines l join erp.sales_orders o on o.id = l.order_id"
        "       where o.id = any(%s::bigint[]) group by 1, 2) s"
        " where i.dealer_id = s.dealer_id and i.part_id = s.part_id",
        (order_ids,),
    )


def replenish_stock(conn: psycopg.Connection, rng: random.Random, state: SimulationState) -> int:
    """Restock rows below their reorder point once their delivery delay has passed."""
    with conn.transaction():
        low = [
            r[0]
            for r in conn.execute(
                "select id from erp.inventory where quantity_on_hand < reorder_point order by id"
            )
        ]
        # Forget deliveries for rows that are no longer low, then schedule the newly low ones.
        still_low = set(low)
        state.due_tick = {i: t for i, t in state.due_tick.items() if i in still_low}
        for inventory_id in low:
            state.due_tick.setdefault(
                inventory_id, state.tick_number + rng.randint(*REPLENISH_DELAY_TICKS)
            )
        arrived = [i for i, t in state.due_tick.items() if t <= state.tick_number]
        for inventory_id in arrived:
            conn.execute(
                "update erp.inventory set quantity_on_hand = reorder_point * %s where id = %s",
                (rng.randint(*REPLENISH_TARGET_MULTIPLE), inventory_id),
            )
            del state.due_tick[inventory_id]
    return len(arrived)


def correct_line_quantities(conn: psycopg.Connection, rng: random.Random) -> int:
    """Late update: a quantity on an order placed more than a day ago is corrected."""
    with conn.transaction():
        lines = conn.execute(
            "select l.id, l.quantity from erp.order_lines l"
            " join erp.sales_orders o on o.id = l.order_id"
            " where o.ordered_at < now() - interval '1 day' and o.status <> 'cancelled'"
            " order by l.id"
        ).fetchall()
        chosen = rng.sample(lines, k=min(len(lines), rng.randint(1, 3)))
        for line_id, quantity in chosen:
            new_quantity = rng.choice(
                [q for q in range(quantity - 2, quantity + 3) if q > 0 and q != quantity]
            )
            conn.execute(
                "update erp.order_lines set quantity = %s where id = %s", (new_quantity, line_id)
            )
    return len(chosen)


def delete_order_lines(conn: psycopg.Connection, rng: random.Random) -> int:
    """Hard-delete the last line of a few open orders that keep at least one other line."""
    with conn.transaction():
        candidates = [
            r[0]
            for r in conn.execute(
                "select l.id from erp.order_lines l join erp.sales_orders o on o.id = l.order_id"
                " where o.status in ('placed', 'confirmed')"
                " and l.line_number > 1"
                " and l.line_number = (select max(x.line_number) from erp.order_lines x"
                "                     where x.order_id = l.order_id)"
                " order by l.id"
            )
        ]
        chosen = rng.sample(candidates, k=min(len(candidates), rng.randint(1, 3)))
        conn.execute("delete from erp.order_lines where id = any(%s::bigint[])", (chosen,))
    return len(chosen)


def change_part_prices(conn: psycopg.Connection, rng: random.Random) -> int:
    with conn.transaction():
        parts = conn.execute("select id, list_price_jpy from erp.parts order by id").fetchall()
        chosen = rng.sample(parts, k=min(len(parts), rng.randint(1, 3)))
        for part_id, price in chosen:
            new_price = (price * Decimal(str(round(rng.uniform(0.9, 1.1), 4)))).quantize(CENT)
            if new_price == price:
                new_price += Decimal("1")
            conn.execute(
                "update erp.parts set list_price_jpy = %s where id = %s", (new_price, part_id)
            )
    return len(chosen)


def move_dealer(conn: psycopg.Connection, rng: random.Random) -> int:
    if rng.random() >= MOVE_DEALER_PROBABILITY:
        return 0
    with conn.transaction():
        dealers = conn.execute(
            "select id, country_code, region from erp.dealers order by id"
        ).fetchall()
        dealer_id, country, region = rng.choice(dealers)
        new_region = rng.choice([r for r in REGIONS[country] if r != region])
        conn.execute("update erp.dealers set region = %s where id = %s", (new_region, dealer_id))
    return 1


def tick(
    conn: psycopg.Connection,
    rng: random.Random,
    state: SimulationState,
    with_deletes: bool = False,
) -> None:
    """One business tick; every behaviour commits in its own transaction."""
    state.tick_number += 1
    log.info(
        "tick new_orders=%d cancelled=%d advanced=%d corrected_lines=%d price_changes=%d"
        " dealer_moves=%d replenished=%d",
        create_orders(conn, rng),
        cancel_placed_orders(conn, rng),
        advance_orders(conn, rng),
        correct_line_quantities(conn, rng),
        change_part_prices(conn, rng),
        move_dealer(conn, rng),
        replenish_stock(conn, rng, state),
    )
    if with_deletes:
        log.info("tick deleted_lines=%d", delete_order_lines(conn, rng))


def simulate(
    settings: Settings,
    *,
    ticks: int | None = None,
    interval: float | None = None,
    seed: int | None = None,
    with_deletes: bool = False,
) -> None:
    """Run `ticks` ticks, or tick every `interval` seconds until SIGINT or SIGTERM."""
    if (ticks is None) == (interval is None):
        raise ValueError("pass exactly one of ticks and interval")
    rng = random.Random(seed)
    state = SimulationState()
    stop = threading.Event()
    signals = (signal.SIGINT, signal.SIGTERM)
    previous = {sig: signal.signal(sig, lambda *_: stop.set()) for sig in signals}
    done = 0
    try:
        with connect(settings, autocommit=True) as conn:
            while not stop.is_set() and (ticks is None or done < ticks):
                tick(conn, rng, state, with_deletes)
                done += 1
                if interval is not None:
                    stop.wait(interval)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    log.info("simulation stopped after %d ticks", done)
