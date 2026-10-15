"""Database boundary for the read-only catalog explorer."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from gamedb.config import PROJECT_ROOT


QUERY_DIRECTORY = PROJECT_ROOT / "sql" / "queries" / "explorer"
UNRESOLVED_TOKEN = re.compile(r"__[A-Z][A-Z0-9_]*__")


def quote_sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sql_integer(value: int, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer greater than or equal to {minimum}")
    return value


class SqlTemplate:
    """Load one reviewable SQL file and bind its validated literal tokens."""

    def __init__(self, path: Path):
        self.path = path

    def render(self, **values: str | int) -> str:
        sql = self.path.read_text(encoding="utf-8")
        for name, value in values.items():
            sql = sql.replace(f"__{name.upper()}__", str(value))
        unresolved = sorted(set(UNRESOLVED_TOKEN.findall(sql)))
        if unresolved:
            raise ValueError(
                f"Unbound SQL token(s) in {self.path.name}: {', '.join(unresolved)}"
            )
        return sql


class PsqlJsonClient:
    """Execute one SQL document through psql and decode its JSON result."""

    def query(self, sql: str):
        completed = subprocess.run(
            ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-Atq", "-c", sql],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = completed.stdout.strip()
        return json.loads(payload or "null")


class CatalogRepository:
    """Provide the explorer's read-only catalog operations."""

    def __init__(self, username: str, client: PsqlJsonClient | None = None):
        self.username = username
        self.client = client or PsqlJsonClient()

    def systems_sql(self) -> str:
        return SqlTemplate(QUERY_DIRECTORY / "systems.sql").render(
            username=quote_sql_text(self.username)
        )

    def titles_sql(
        self, system_id: int, limit: int, offset: int, title_filter: str = ""
    ) -> str:
        return SqlTemplate(QUERY_DIRECTORY / "titles.sql").render(
            username=quote_sql_text(self.username),
            system_id=sql_integer(system_id, "system_id", 1),
            limit=sql_integer(limit, "limit", 1),
            offset=sql_integer(offset, "offset"),
            title_filter=quote_sql_text(title_filter),
        )

    def title_releases_sql(self, title_id: int) -> str:
        return SqlTemplate(QUERY_DIRECTORY / "title_releases.sql").render(
            username=quote_sql_text(self.username),
            title_id=sql_integer(title_id, "title_id", 1),
        )

    def systems(self):
        return self.client.query(self.systems_sql())

    def titles(
        self, system_id: int, limit: int, offset: int, title_filter: str = ""
    ):
        return self.client.query(
            self.titles_sql(system_id, limit, offset, title_filter)
        )

    def title_releases(self, title_id: int):
        return self.client.query(self.title_releases_sql(title_id))
