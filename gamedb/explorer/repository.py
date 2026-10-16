"""Database boundary for catalog exploration and working corrections."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from gamedb.config import PROJECT_ROOT


QUERY_DIRECTORY = PROJECT_ROOT / "sql" / "queries" / "explorer"
UNRESOLVED_TOKEN = re.compile(r"__[A-Z][A-Z0-9_]*__")
CONTENT_SIGNATURE = re.compile(r"[0-9a-f]{32}")


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
    """Provide catalog reads and validated working-correction writes."""

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

    def software_releases_sql(self, software_id: int) -> str:
        return SqlTemplate(QUERY_DIRECTORY / "title_releases.sql").render(
            username=quote_sql_text(self.username),
            software_id=sql_integer(software_id, "software_id", 1),
        )

    def correction_targets_sql(
        self, system_id: int, exclude_software_id: int, title_filter: str
    ) -> str:
        return SqlTemplate(QUERY_DIRECTORY / "correction_targets.sql").render(
            system_id=sql_integer(system_id, "system_id", 1),
            exclude_software_id=sql_integer(
                exclude_software_id, "exclude_software_id"
            ),
            title_filter=quote_sql_text(title_filter[:100]),
        )

    @staticmethod
    def _signature(value: str | None, name: str, required: bool = True) -> str:
        if value is None and not required:
            return ""
        if not isinstance(value, str) or not CONTENT_SIGNATURE.fullmatch(value):
            raise ValueError(f"{name} must be a 32-character content signature")
        return value

    def create_correction_sql(
        self, system_id: int, subject_signature: str, action: str,
        target_signature: str | None, note: str,
    ) -> str:
        if action not in ("assign", "separate"):
            raise ValueError("action must be assign or separate")
        subject = self._signature(subject_signature, "subject_signature")
        target = self._signature(
            target_signature, "target_signature", required=action == "assign"
        )
        if action == "assign" and subject == target:
            raise ValueError("subject and target signatures must differ")
        return SqlTemplate(QUERY_DIRECTORY / "create_correction.sql").render(
            system_id=sql_integer(system_id, "system_id", 1),
            subject_signature=quote_sql_text(subject),
            action=quote_sql_text(action),
            target_signature=quote_sql_text(target),
            note=quote_sql_text(note.strip()[:1000]),
            username=quote_sql_text(self.username),
        )

    def disable_correction_sql(self, correction_id: int) -> str:
        return SqlTemplate(QUERY_DIRECTORY / "disable_correction.sql").render(
            correction_id=sql_integer(correction_id, "correction_id", 1)
        )

    def systems(self):
        return self.client.query(self.systems_sql())

    def titles(
        self, system_id: int, limit: int, offset: int, title_filter: str = ""
    ):
        return self.client.query(
            self.titles_sql(system_id, limit, offset, title_filter)
        )

    def software_releases(self, software_id: int):
        return self.client.query(self.software_releases_sql(software_id))

    def correction_targets(
        self, system_id: int, exclude_software_id: int, title_filter: str
    ):
        return self.client.query(self.correction_targets_sql(
            system_id, exclude_software_id, title_filter
        ))

    def create_correction(
        self, system_id: int, subject_signature: str, action: str,
        target_signature: str | None, note: str,
    ):
        return self.client.query(self.create_correction_sql(
            system_id, subject_signature, action, target_signature, note
        ))

    def disable_correction(self, correction_id: int):
        return self.client.query(self.disable_correction_sql(correction_id))
