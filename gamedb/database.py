"""Shared SQLAlchemy connection configuration."""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL

from .config import ProjectEnvironment


def database_url() -> URL:
    """Build a PostgreSQL URL without interpolating credentials into text."""
    ProjectEnvironment().load()
    return URL.create(
        "postgresql+psycopg",
        username=os.environ.get("PGUSER"),
        password=os.environ.get("PGPASSWORD"),
        host=os.environ.get("PGHOST"),
        port=int(os.environ["PGPORT"]) if os.environ.get("PGPORT") else None,
        database=os.environ.get("PGDATABASE"),
        query={"sslmode": os.environ["PGSSLMODE"]}
        if os.environ.get("PGSSLMODE")
        else {},
    )


def create_database_engine() -> Engine:
    """Create the explicit database boundary used by derivation services."""
    return create_engine(database_url(), future=True)
