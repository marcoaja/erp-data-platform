import psycopg

from erp_platform.config import Settings


def connect(
    settings: Settings, *, reader: bool = False, autocommit: bool = False
) -> psycopg.Connection:
    """Open a connection as the owner role, or as the read-only role when `reader` is set."""
    return psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.erp_reader_user if reader else settings.postgres_user,
        password=settings.erp_reader_password if reader else settings.postgres_password,
        connect_timeout=5,
        autocommit=autocommit,
    )
