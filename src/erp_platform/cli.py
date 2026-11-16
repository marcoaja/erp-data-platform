import argparse
import logging
import sys
from collections.abc import Sequence

from erp_platform.config import Settings, load_settings
from erp_platform.db import connect
from erp_platform.erp.migrate import migrate

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
    except Exception:
        log.exception("command failed: %s", args.command)
        sys.exit(1)
