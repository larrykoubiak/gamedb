"""Create the schemas owned by the derivation package."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .schema import metadata
from gamedb.integrated.schema import metadata as integrated_metadata


class DerivedSchemaManager:
    """Reset disposable projections while retaining staging and app preferences."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def reset(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS staging"))
            integrated_metadata.create_all(connection)
            connection.execute(text("DROP SCHEMA IF EXISTS catalog CASCADE"))
            connection.execute(text("DROP SCHEMA IF EXISTS derived CASCADE"))
            connection.execute(text("DROP SCHEMA IF EXISTS ref CASCADE"))
            connection.execute(text("CREATE SCHEMA ref"))
            connection.execute(text("CREATE SCHEMA derived"))
            metadata.create_all(connection)
