"""Project-level runtime configuration."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ProjectEnvironment:
    """Load recognized, missing settings from the project environment file."""

    KEYS = frozenset({
        "GAMEDB_EXPLORER_PORT",
        "GAMEDB_ENABLE_CORRECTIONS",
        "PGDATABASE",
        "PGHOST",
        "PGPASSWORD",
        "PGPORT",
        "PGSSLMODE",
        "PGUSER",
    })

    def __init__(self, path: Path = PROJECT_ROOT / ".env"):
        self.path = path

    def load(self) -> tuple[str, ...]:
        if not self.path.is_file():
            return ()

        loaded = []
        for raw_line in self.path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, separator, value = line.partition("=")
            key = key.strip()
            if not separator or key not in self.KEYS or key in os.environ:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            os.environ[key] = value
            loaded.append(key)
        return tuple(loaded)
