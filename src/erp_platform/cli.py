import argparse
import logging
import sys
from collections.abc import Sequence

from erp_platform.config import Settings, load_settings
from erp_platform.db import connect
from erp_platform.erp.migrate import migrate
from erp_platform.erp.seed import seed
from erp_platform.erp.simulate import simulate
from erp_platform.ingestion.extract import extract
from erp_platform.pipeline import run, transform

log = logging.getLogger("erp_platform")


def db_ping(settings: Settings) -> None:
    with connect(settings) as conn:
        row = conn.execute("select version()").fetchone()
    if row is None:
        raise RuntimeError("select version() returned no row")
    print(row[0])
    log.info("postgres reachable host=%s port=%s", settings.postgres_host, settings.postgres_port)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="erp")
    commands = parser.add_subparsers(dest="command", required=True)

    db = commands.add_parser("db", help="database commands").add_subparsers(
        dest="db_command", required=True
    )
    db.add_parser("ping", help="connect and print the Postgres version")
    db.add_parser("migrate", help="apply pending SQL migrations")

    seed_cmd = commands.add_parser("seed", help="load master data and 90 days of orders")
    seed_cmd.add_argument("--seed", type=int, default=42, help="random seed (default 42)")

    sim = commands.add_parser("simulate", help="run business ticks against the ERP")
    mode = sim.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ticks", type=int, help="run N ticks and exit")
    mode.add_argument("--interval", type=float, help="tick forever, S seconds apart")
    sim.add_argument("--seed", type=int, help="fix the random generator")
    commands.add_parser("extract", help="copy changed ERP rows into the raw layer")
    commands.add_parser("transform", help="build the warehouse with dbt")
    commands.add_parser("run", help="extract, then transform; stops at the first failure")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    args = build_parser().parse_args(argv)
    try:
        if args.command == "db":
            if args.db_command == "ping":
                db_ping(load_settings())
            elif args.db_command == "migrate":
                migrate(load_settings())
        elif args.command == "seed":
            seed(load_settings(), seed=args.seed)
        elif args.command == "simulate":
            simulate(load_settings(), ticks=args.ticks, interval=args.interval, seed=args.seed)
        elif args.command == "extract":
            extract(load_settings())
        elif args.command == "transform":
            transform(load_settings())
        elif args.command == "run":
            run(load_settings())
    except Exception:
        log.exception("command failed: %s", args.command)
        sys.exit(1)
