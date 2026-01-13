"""Import media thumbnails into the database."""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import Media, Release, System, Title


MEDIA_TYPE_MAP = {
    "named_boxarts": "boxart",
    "named_snaps": "snapshot",
    "named_titles": "title",
    "named_logos": "logo",
}

REGION_RE = re.compile(r"\(([^)]+)\)\s*$")
TRAILING_GROUP_RE = re.compile(r"\s*(\[[^\]]*\]|\([^\)]*\))\s*$")
TRAILING_VERSION_RE = re.compile(r"\s+v?\d+(?:\.\d+)*$", re.IGNORECASE)
TRAILING_REV_RE = re.compile(r"\s+rev\s*[0-9a-z]+$", re.IGNORECASE)
SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass
class MediaImportStats:
    files_scanned: int = 0
    titles_matched: int = 0
    releases_matched: int = 0
    media_created: int = 0
    skipped_existing: int = 0
    skipped_unknown_system: int = 0
    skipped_unknown_title: int = 0
    skipped_unknown_type: int = 0
    skipped_ambiguous_release: int = 0
    skipped_unmatched_release: int = 0


class MediaImporter:
    def __init__(
        self,
        session: Session,
        media_root: str,
        dry_run: bool = False,
        skipped_log_path: Optional[str] = None,
    ):
        self.session = session
        self.media_root = media_root
        self.dry_run = dry_run
        self.skipped_log_path = skipped_log_path

    def import_path(self, path: str, limit: Optional[int] = None) -> MediaImportStats:
        stats = MediaImportStats()
        root = self._resolve_root(path)
        if not self.dry_run:
            print("[media] truncating media table")
            self.session.execute(text("TRUNCATE media"))
            self.session.commit()
        for system_dir in self._iter_system_dirs(root):
            system_name = system_dir.name
            system = self.session.execute(
                select(System).where(System.name == system_name)
            ).scalar_one_or_none()
            if not system:
                stats.skipped_unknown_system += 1
                self._log_skipped("unknown_system", system_name)
                continue

            system_files = 0
            start_media_created = stats.media_created
            start_skipped = self._total_skipped(stats)
            print(f"[media] system={system_name} starting")
            titles = self._load_titles(system.id)
            releases = self._load_releases(list(titles.values()))

            for full_path in self._iter_system_media_files(system_dir.path):
                stats.files_scanned += 1
                system_files += 1
                if limit is not None and stats.files_scanned > limit:
                    break
                if system_files % 5000 == 0:
                    matched = stats.media_created - start_media_created
                    skipped = self._total_skipped(stats) - start_skipped
                    print(
                        f"[media] system={system_name} scanned={system_files} "
                        f"matched={matched} skipped={skipped}"
                    )
                self._handle_file(full_path, root, system, titles, releases, stats)
            matched = stats.media_created - start_media_created
            skipped = self._total_skipped(stats) - start_skipped
            print(
                f"[media] system={system_name} scanned={system_files} "
                f"matched={matched} skipped={skipped} done"
            )
            if not self.dry_run:
                self.session.commit()
            if limit is not None and stats.files_scanned >= limit:
                break
        return stats

    def _iter_system_dirs(self, root: str) -> Iterable[os.DirEntry]:
        with os.scandir(root) as entries:
            for entry in entries:
                if entry.is_dir():
                    yield entry

    def _iter_system_media_files(self, system_path: str) -> Iterable[str]:
        for folder in os.scandir(system_path):
            if not folder.is_dir():
                continue
            for dir_root, _dirs, files in os.walk(folder.path):
                for filename in files:
                    ext = os.path.splitext(filename)[1].lower()
                    if ext not in SUPPORTED_EXTS:
                        continue
                    yield os.path.join(dir_root, filename)

    def _handle_file(
        self,
        full_path: str,
        root: str,
        system: System,
        titles: Dict[str, int],
        releases: Dict[int, List[Tuple[int, Optional[str], Optional[str]]]],
        stats: MediaImportStats,
    ) -> None:
        rel_path = os.path.relpath(full_path, root)
        parts = rel_path.split(os.sep)
        if len(parts) < 3:
            self._log_skipped("path_too_short", rel_path)
            stats.skipped_unknown_type += 1
            return

        type_folder = parts[1].lower()
        media_type = MEDIA_TYPE_MAP.get(type_folder)
        if not media_type:
            stats.skipped_unknown_type += 1
            self._log_skipped("unknown_media_type", rel_path)
            return

        filename = parts[-1]
        title_name = os.path.splitext(filename)[0]
        title_id = self._find_title_id(title_name, titles)
        if not title_id:
            stats.skipped_unknown_title += 1
            self._log_skipped("unknown_title", rel_path)
            return
        stats.titles_matched += 1

        release_list = releases.get(title_id, [])
        release_id, reason = self._match_release(release_list, title_name)
        if release_id is None:
            if reason == "ambiguous_release":
                stats.skipped_ambiguous_release += 1
            else:
                stats.skipped_unmatched_release += 1
            self._log_skipped(reason or "unmatched_release", rel_path)
            return
        stats.releases_matched += 1

        db_path = os.path.relpath(full_path, self.media_root).replace(os.sep, "/")
        existing = self.session.execute(
            select(Media).where(
                Media.release_id == release_id,
                Media.media_type == media_type,
                Media.path == db_path,
            )
        ).scalar_one_or_none()
        if existing:
            stats.skipped_existing += 1
            return

        if not self.dry_run:
            self.session.add(
                Media(release_id=release_id, media_type=media_type, path=db_path)
            )
        stats.media_created += 1

    def _match_release(
        self,
        releases: List[Tuple[int, Optional[str], Optional[str]]],
        title_name: str,
    ) -> Tuple[Optional[int], Optional[str]]:
        if not releases:
            return None, "no_releases"
        if len(releases) == 1:
            return releases[0][0], None

        for release_id, _region, display_name in releases:
            if display_name and display_name == title_name:
                return release_id, None

        match = REGION_RE.search(title_name)
        if match:
            region = match.group(1)
            matches = [rel for rel in releases if rel[1] == region]
            if len(matches) == 1:
                return matches[0][0], None
            if len(matches) > 1:
                return None, "ambiguous_release"

        null_region = [rel for rel in releases if rel[1] is None]
        if len(null_region) == 1:
            return null_region[0][0], None

        return None, "ambiguous_release"

    def _resolve_root(self, path: str) -> str:
        thumbnail_path = os.path.join(path, "thumbnails")
        if os.path.isdir(thumbnail_path):
            return thumbnail_path
        return path

    def _find_title_id(self, title_name: str, titles: Dict[str, int]) -> Optional[int]:
        normalized = self._normalize_title(title_name)
        if normalized in titles:
            return titles[normalized]

        for candidate in self._iter_title_candidates(title_name):
            normalized_candidate = self._normalize_title(candidate)
            if normalized_candidate in titles:
                return titles[normalized_candidate]
        return None

    def _iter_title_candidates(self, title_name: str) -> Iterable[str]:
        seen = set()
        current = self._normalize_title(title_name)
        while current and current not in seen:
            seen.add(current)
            yield current
            trimmed = TRAILING_GROUP_RE.sub("", current).strip()
            if trimmed == current:
                break
            current = trimmed

        for candidate in list(seen):
            stripped = TRAILING_VERSION_RE.sub("", candidate).strip()
            stripped = TRAILING_REV_RE.sub("", stripped).strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                yield stripped

    @staticmethod
    def _normalize_title(title_name: str) -> str:
        normalized = unicodedata.normalize("NFKC", title_name)
        normalized = " ".join(normalized.split()).strip()
        normalized = normalized.replace(")(", ") (")
        return normalized.casefold()

    def _load_titles(self, system_id: int) -> Dict[str, int]:
        rows = self.session.execute(
            select(Title.id, Title.name).where(Title.system_id == system_id)
        ).all()
        mapping: Dict[str, int] = {}
        for title_id, name in rows:
            normalized = self._normalize_title(name)
            mapping.setdefault(normalized, title_id)
        return mapping

    @staticmethod
    def _total_skipped(stats: MediaImportStats) -> int:
        return (
            stats.skipped_existing
            + stats.skipped_unknown_title
            + stats.skipped_unknown_type
            + stats.skipped_unknown_system
            + stats.skipped_ambiguous_release
            + stats.skipped_unmatched_release
        )

    def _load_releases(
        self, title_ids: List[int]
    ) -> Dict[int, List[Tuple[int, Optional[str], Optional[str]]]]:
        if not title_ids:
            return {}
        rows = self.session.execute(
            select(Release.id, Release.title_id, Release.region, Release.display_name).where(
                Release.title_id.in_(title_ids)
            )
        ).all()
        mapping: Dict[int, List[Tuple[int, Optional[str], Optional[str]]]] = {}
        for release_id, title_id, region, display_name in rows:
            mapping.setdefault(title_id, []).append((release_id, region, display_name))
        return mapping

    def _log_skipped(self, reason: str, rel_path: str) -> None:
        if not self.skipped_log_path:
            return
        try:
            with open(self.skipped_log_path, "a", encoding="utf-8") as handle:
                handle.write(f"{reason} path={rel_path}\n")
        except Exception:
            return
