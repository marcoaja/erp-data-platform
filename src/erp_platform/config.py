import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read settings from `env`, defaulting to the process environment."""
    env = os.environ if env is None else env

    def require(name: str) -> str:
        value = env.get(name)
        if not value:
            raise RuntimeError(f"Missing required environment variable: {name}")
        return value

    return Settings(
        postgres_host=require("POSTGRES_HOST"),
        postgres_port=int(require("POSTGRES_PORT")),
        postgres_db=require("POSTGRES_DB"),
        postgres_user=require("POSTGRES_USER"),
        postgres_password=require("POSTGRES_PASSWORD"),
    )
