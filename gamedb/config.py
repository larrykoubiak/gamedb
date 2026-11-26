"""Project-level runtime configuration."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ProjectEnvironment:
    """Load recognized, missing settings from the project environment file."""

    KEYS = frozenset({
        "GAMEDB_EXPLORER_PORT",
        "GAMEDB_API_KEY",
        "GAMEDB_ENABLE_CORRECTIONS",
        "GAMEDB_LIBRETRO_THUMBNAILS",
        "GAMEDB_MEDIA_INDEX",
        "GAMEDB_LAUNCHBOX_IMAGE_CACHE",
        "GAMEDB_PREVIEW_CACHE",
        "GAMEDB_MEDIA_USERNAME",
        "GAMEDB_MEGADRIVE_MANUAL_ROOT",
        "GAMEDB_MASTERSYSTEM_MANUAL_ROOT",
        "GAMEDB_MASTERSYSTEM_TRANSLATION_ROOT",
        "GAMEDB_MEGADRIVE_TRANSLATION_ROOT",
        "GAMEDB_NEOGEO_MANUAL_ROOT",
        "GAMEDB_NEOGEO_TRANSLATION_ROOT",
        "GAMEDB_NES_MANUAL_ROOT",
        "GAMEDB_NES_TRANSLATION_ROOT",
        "GAMEDB_PCENGINE_MANUAL_ROOT",
        "GAMEDB_PCENGINE_TRANSLATION_ROOT",
        "GAMEDB_N64_MANUAL_ROOT",
        "GAMEDB_N64_TRANSLATION_ROOT",
        "GAMEDB_SATURN_MANUAL_ROOT",
        "GAMEDB_JAGUAR_MANUAL_ROOT",
        "GAMEDB_ATARI7800_MANUAL_ROOT",
        "GAMEDB_PCFX_MANUAL_ROOT",
        "GAMEDB_CD32_MANUAL_ROOT",
        "GAMEDB_3DO_MANUAL_ROOT",
        "GAMEDB_PLAYDIA_MANUAL_ROOT",
        "GAMEDB_PIPPIN_MANUAL_ROOT",
        "GAMEDB_DREAMCAST_MANUAL_ROOT",
        "GAMEDB_PLAYSTATION2_MANUAL_ROOT",
        "GAMEDB_GAMECUBE_MANUAL_ROOT",
        "GAMEDB_DREAMCAST_TRANSLATION_ROOT",
        "GAMEDB_PLAYSTATION2_TRANSLATION_ROOT",
        "GAMEDB_GAMECUBE_TRANSLATION_ROOT",
        "GAMEDB_PCFX_TRANSLATION_ROOT",
        "GAMEDB_3DO_TRANSLATION_ROOT",
        "GAMEDB_SATURN_TRANSLATION_ROOT",
        "GAMEDB_PLAYSTATION_MANUAL_ROOT",
        "GAMEDB_PLAYSTATION_TRANSLATION_ROOT",
        "GAMEDB_INTEGRATED_ROOT",
        "GAMEDB_ROM_ROOT",
        "GAMEDB_SNES_MANUAL_ROOT",
        "GAMEDB_SNES_TRANSLATION_ROOT",
        "GAMEDB_VGM_ROOT",
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
