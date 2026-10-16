"""Shared SQLAlchemy connection configuration."""

from __future__ import annotations

import os
from importlib.util import find_spec

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL

from .config import ProjectEnvironment


def database_url() -> URL:
    """Build a PostgreSQL URL without interpolating credentials into text."""
    ProjectEnvironment().load()
    # Production images install psycopg 3. Some recovery/workstation
    # environments still provide psycopg2; selecting the available driver
    # keeps one explicit URL builder without interpolating credentials.
    driver = "postgresql+psycopg" if find_spec("psycopg") else "postgresql+psycopg2"
    return URL.create(
        driver,
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
