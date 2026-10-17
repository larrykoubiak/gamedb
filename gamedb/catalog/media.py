"""Build the disposable Libretro thumbnail projection for catalog software."""

from __future__ import annotations

from collections import defaultdict
import csv
from dataclasses import dataclass
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from sqlalchemy import text
from sqlalchemy.engine import Engine

from gamedb.derive.extractors.archive_name_extract import ArchiveNameExtractor


PROFILES = ("No-Intro", "Redump", "TOSEC", "TOSEC-ISO")
BAD_CHARS = str.maketrans({character: "_" for character in '&*/:`<>?\\|'})
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})
KINDS = {
    "Named_Boxarts": ("boxart", 0),
    "Named_Boxarts_1024": ("boxart", 1),
    "Named_Snaps": ("snap", 0),
    "Named_Titles": ("title", 0),
    "Named_Logos": ("logo", 0),
}


@dataclass(frozen=True)
class Asset:
    relative_path: str
    directory: str
    file_name: str
    kind: str
    quality: int


@dataclass(frozen=True)
class Release:
    software_id: int
    system: tuple[str, str]
    title: str
    regions: frozenset[str]
    score: int
    preferred: bool


@dataclass(frozen=True)
class Choice:
    asset: Asset
    basis: str
    region_match: str
    source_release_id: int | None
    rank: tuple


def region_compatibility(
    image_regions: frozenset[str], target_regions: frozenset[str]
) -> tuple[str, int]:
    """Return an explainable compatibility label and deterministic rank."""
    if not image_regions or not target_regions:
        return "unknown", 1
    if image_regions == target_regions:
        return "exact", 5
    if "WORLD" in image_regions:
        return "world", 4
    if image_regions & target_regions:
        return "overlap", 4
    return "mismatch", 0


class ThumbnailPathIndex:
    """Read a cached path index, refreshing it cheaply from Git when possible."""

    def __init__(self, root: Path, cache_path: Path):
        self.root = root
        self.cache_path = cache_path
        self.metadata_path = cache_path.with_suffix(cache_path.suffix + ".json")

    def paths(self):
        if self.root.is_dir():
            revision = self._revision()
            if (
                (revision and not self._cache_matches(revision))
                or not self.cache_path.is_file()
            ):
                self._refresh(revision)
        if not self.cache_path.is_file():
            raise FileNotFoundError(
                "Libretro thumbnails are unavailable: set "
                "GAMEDB_LIBRETRO_THUMBNAILS to the checkout or "
                "GAMEDB_MEDIA_INDEX to a cached path index"
            )
        with gzip.open(self.cache_path, "rt", encoding="utf-8") as handle:
            yield from (line.rstrip("\n") for line in handle)

    def _cache_matches(self, revision: str) -> bool:
        if not self.cache_path.is_file() or not self.metadata_path.is_file():
            return False
        try:
            metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return metadata.get("revision") == revision

    def _revision(self) -> str | None:
        git = shutil.which("git")
        if git and (self.root / ".git").exists():
            return subprocess.run(
                [git, "-C", str(self.root), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
        head_path = self.root / ".git/HEAD"
        if not head_path.is_file():
            return None
        head = head_path.read_text(encoding="ascii").strip()
        if not head.startswith("ref: "):
            return head
        reference = head[5:]
        loose_reference = self.root / ".git" / reference
        if loose_reference.is_file():
            return loose_reference.read_text(encoding="ascii").strip()
        packed_references = self.root / ".git/packed-refs"
        if packed_references.is_file():
            for line in packed_references.read_text(encoding="ascii").splitlines():
                revision, separator, name = line.partition(" ")
                if separator and name == reference:
                    return revision
        return None

    def _refresh(self, revision: str | None) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        git = shutil.which("git")
        if git and (self.root / ".git").exists():
            completed = subprocess.run(
                [git, "-C", str(self.root), "ls-files", "-z"],
                check=True, capture_output=True,
            )
            paths = completed.stdout.decode("utf-8").split("\0")
        else:
            paths = self._filesystem_paths()
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.cache_path.parent, prefix=self.cache_path.name + "."
        )
        try:
            with os.fdopen(descriptor, "wb") as raw_handle:
                with gzip.open(raw_handle, "wt", encoding="utf-8") as handle:
                    for path in paths:
                        if path:
                            handle.write(path + "\n")
            os.replace(temporary_name, self.cache_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        self.metadata_path.write_text(
            json.dumps({"revision": revision}) + "\n", encoding="utf-8"
        )

    def _filesystem_paths(self):
        for directory, child_directories, file_names in os.walk(self.root):
            child_directories[:] = [
                name for name in child_directories if name != ".git"
            ]
            relative_directory = Path(directory).relative_to(self.root)
            for file_name in file_names:
                yield (relative_directory / file_name).as_posix()


class MediaCatalogBuilder:
    """Select and persist one best available image per software and kind."""

    def __init__(
        self, engine: Engine, project_root: Path, thumbnail_root: Path,
        index_path: Path, username: str = "default",
    ):
        self.engine = engine
        self.project_root = project_root
        self.thumbnail_root = thumbnail_root
        self.index_path = index_path
        self.username = username

    @classmethod
    def from_environment(
        cls, engine: Engine, project_root: Path
    ) -> "MediaCatalogBuilder":
        root = Path(os.environ.get(
            "GAMEDB_LIBRETRO_THUMBNAILS", "/data/libretro-thumbnails"
        ))
        index = Path(os.environ.get(
            "GAMEDB_MEDIA_INDEX", "/data/media/cache/libretro-thumbnail-index.paths.gz"
        ))
        return cls(
            engine, project_root, root, index,
            os.environ.get("GAMEDB_MEDIA_USERNAME", "default"),
        )

    def execute(self) -> dict[str, int]:
        folder_systems, system_folders = self._load_mapping()
        images = self._load_images(folder_systems)
        if not images:
            raise RuntimeError("No mapped Libretro thumbnail paths were found")
        releases, preferred_regions, title_software = self._load_releases(
            system_folders
        )
        if not releases:
            raise RuntimeError(
                f"No scored releases were found for media user {self.username!r}"
            )
        choices = self._select(
            images, folder_systems, system_folders, releases,
            preferred_regions, title_software,
        )
        if not choices:
            raise RuntimeError(
                "Media matching selected no assets; preserving the existing projection"
            )
        self._replace_projection(choices)
        software_count = len({software_id for software_id, _ in choices})
        print(
            f"  media: {len(choices):,} associations across "
            f"{software_count:,} software", flush=True,
        )
        for kind in ("boxart", "snap", "title", "logo"):
            count = sum(selected_kind == kind for _, selected_kind in choices)
            print(f"    {kind}: {count:,}", flush=True)
        return {
            "assets": len({choice.asset.relative_path for choice in choices.values()}),
            "associations": len(choices),
            "software": software_count,
        }

    def _load_mapping(self):
        mapping_path = self.project_root / "reference/libretro_thumbnail_systems.csv"
        folder_systems = defaultdict(list)
        system_folders = {}
        with mapping_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            required = {
                "canonical_manufacturer_name", "canonical_system_name",
                "libretro_directory",
            }
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise ValueError(f"Invalid Libretro system mapping: {mapping_path}")
            for row in reader:
                system = (
                    row["canonical_manufacturer_name"].strip(),
                    row["canonical_system_name"].strip(),
                )
                folder = row["libretro_directory"].strip()
                if not all(system) or not folder:
                    raise ValueError(f"Blank Libretro system mapping: {mapping_path}")
                if system in system_folders:
                    raise ValueError(
                        "Duplicate canonical system in Libretro mapping: "
                        f"{system[0]} / {system[1]}"
                    )
                folder_systems[folder].append(system)
                system_folders[system] = folder
        if not system_folders:
            raise ValueError(f"Empty Libretro system mapping: {mapping_path}")
        return folder_systems, system_folders

    def _load_images(self, folder_systems):
        images = defaultdict(lambda: defaultdict(list))
        path_index = ThumbnailPathIndex(self.thumbnail_root, self.index_path)
        for path in path_index.paths():
            parts = path.split("/", 2)
            if (
                len(parts) != 3
                or parts[0] not in folder_systems
                or parts[1] not in KINDS
            ):
                continue
            stem, extension = os.path.splitext(parts[2])
            if extension.lower() not in IMAGE_EXTENSIONS:
                continue
            kind, quality = KINDS[parts[1]]
            images[parts[0]][stem].append(Asset(
                path, parts[0], parts[2], kind, quality
            ))
        print(
            f"  media: indexed {sum(map(len, images.values())):,} mapped names",
            flush=True,
        )
        return images

    def _load_releases(self, system_folders):
        query = text("""
            SELECT software.id AS software_id,
                   system.manufacturer_name, system.system_name,
                   release.id AS release_id,
                   release.display_title, score.score,
                   (preferred.release_id = release.id) AS preferred,
                   coalesce(array_agg(DISTINCT fact.fact_value)
                       FILTER (WHERE fact.fact_key = 'region'),
                       ARRAY[]::text[]) AS regions
            FROM catalog.software software
            JOIN catalog.system system ON system.id = software.system_id
            JOIN catalog.software_release membership
              ON membership.software_id = software.id
            JOIN catalog.release release ON release.id = membership.release_id
            JOIN app.app_user user_account ON user_account.username = :username
            JOIN app.user_release_score score
              ON score.user_id = user_account.id
             AND score.release_id = release.id
            JOIN app.user_preferred_release preferred
              ON preferred.user_id = user_account.id
             AND preferred.software_id = software.id
            LEFT JOIN catalog.release_fact fact
              ON fact.release_id = release.id AND fact.fact_key = 'region'
            GROUP BY software.id, system.manufacturer_name, system.system_name,
                     release.id, release.display_title, score.score,
                     preferred.release_id
            ORDER BY software.id, release.id
        """)
        releases = {}
        preferred_regions = {}
        title_software = defaultdict(set)
        with self.engine.connect().execution_options(stream_results=True) as connection:
            rows = connection.execute(query, {"username": self.username})
            for row in rows:
                system = (row.manufacturer_name, row.system_name)
                release = Release(
                    row.software_id, system, row.display_title,
                    frozenset(row.regions),
                    row.score, row.preferred,
                )
                releases[row.release_id] = release
                title_software[(system, release.title)].add(release.software_id)
                if release.preferred:
                    preferred_regions[release.software_id] = release.regions
        mapped = sum(
            release.system in system_folders for release in releases.values()
        )
        print(
            f"  media: loaded {len(releases):,} releases ({mapped:,} mapped)",
            flush=True,
        )
        return releases, preferred_regions, title_software

    def _select(
        self, images, folder_systems, system_folders, releases,
        preferred_regions, title_software,
    ):
        choices = {}

        def consider(
            software_id, asset, basis, image_regions,
            source_release_id=None, source_score=0,
        ):
            region_match, region_rank = region_compatibility(
                image_regions, preferred_regions.get(software_id, frozenset())
            )
            basis_rank = {
                "preferred_release_exact": 3,
                "software_release_exact": 2,
                "software_title_fallback": 1,
            }[basis]
            rank = (
                int(basis == "preferred_release_exact"), region_rank, basis_rank,
                source_score, asset.quality, asset.relative_path,
            )
            key = (software_id, asset.kind)
            if key not in choices or rank > choices[key].rank:
                choices[key] = Choice(
                    asset, basis, region_match, source_release_id, rank
                )

        exact_names = set()
        package_query = text("""
            SELECT membership.release_id, package.archive_name
            FROM catalog.release_package membership
            JOIN catalog.package package ON package.id = membership.package_id
            ORDER BY membership.release_id
        """)
        with self.engine.connect().execution_options(stream_results=True) as connection:
            for release_id, archive_name in connection.execute(package_query):
                release = releases.get(release_id)
                if release is None:
                    continue
                folder = system_folders.get(release.system)
                if folder is None:
                    continue
                stem = os.path.splitext(archive_name)[0]
                matched_stem = stem if stem in images[folder] else stem.translate(BAD_CHARS)
                assets = images[folder].get(matched_stem)
                if not assets:
                    continue
                exact_names.add((folder, matched_stem))
                basis = (
                    "preferred_release_exact" if release.preferred
                    else "software_release_exact"
                )
                for asset in assets:
                    consider(
                        release.software_id, asset, basis, release.regions,
                        release_id, release.score,
                    )

        extractor = ArchiveNameExtractor()
        parsed_names = 0
        for folder, names in images.items():
            for stem, assets in names.items():
                if (folder, stem) in exact_names:
                    continue
                interpretations = set()
                for profile in PROFILES:
                    result = extractor.extract(profile, stem + ".zip")
                    if result.parse_status != "parsed" or len(result.records) != 1:
                        continue
                    record = result.records[0]
                    regions = frozenset(
                        assertion.value for assertion in record.assertions
                        if assertion.key == "region"
                    )
                    interpretations.add((record.title, regions))
                if not interpretations:
                    continue
                parsed_names += 1
                for system in folder_systems[folder]:
                    for title, regions in interpretations:
                        for software_id in title_software.get((system, title), ()):
                            for asset in assets:
                                consider(
                                    software_id, asset,
                                    "software_title_fallback", regions,
                                )
        print(
            f"  media: {len(exact_names):,} exact and "
            f"{parsed_names:,} parsed unmatched names", flush=True,
        )
        return choices

    def _replace_projection(self, choices) -> None:
        assets = {
            choice.asset.relative_path: choice.asset for choice in choices.values()
        }
        ddl = text("""
            DROP TABLE IF EXISTS catalog.software_media;
            DROP TABLE IF EXISTS catalog.media;
            CREATE TABLE catalog.media (
                id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                provider text NOT NULL CHECK (provider = 'libretro-thumbnails'),
                media_kind text NOT NULL
                    CHECK (media_kind IN ('boxart', 'snap', 'title', 'logo')),
                source_system_directory text NOT NULL,
                file_name text NOT NULL,
                relative_path text NOT NULL,
                UNIQUE (provider, relative_path),
                UNIQUE (id, media_kind)
            );
            CREATE TABLE catalog.software_media (
                software_id bigint NOT NULL
                    REFERENCES catalog.software(id) ON DELETE CASCADE,
                media_kind text NOT NULL
                    CHECK (media_kind IN ('boxart', 'snap', 'title', 'logo')),
                media_id bigint NOT NULL,
                match_basis text NOT NULL CHECK (match_basis IN (
                    'preferred_release_exact', 'software_release_exact',
                    'software_title_fallback'
                )),
                region_match text NOT NULL CHECK (region_match IN (
                    'exact', 'overlap', 'world', 'unknown', 'mismatch'
                )),
                source_release_id bigint
                    REFERENCES catalog.release(id) ON DELETE SET NULL,
                PRIMARY KEY (software_id, media_kind),
                UNIQUE (software_id, media_id),
                FOREIGN KEY (media_id, media_kind)
                    REFERENCES catalog.media(id, media_kind) ON DELETE CASCADE,
                CHECK (
                    (match_basis = 'software_title_fallback'
                        AND source_release_id IS NULL)
                    OR
                    (match_basis <> 'software_title_fallback'
                        AND source_release_id IS NOT NULL)
                )
            );
        """)
        insert_media = text("""
            INSERT INTO catalog.media (
                provider, media_kind, source_system_directory,
                file_name, relative_path
            ) VALUES (
                'libretro-thumbnails', :kind, :directory, :file_name, :path
            )
        """)
        insert_association = text("""
            INSERT INTO catalog.software_media (
                software_id, media_kind, media_id, match_basis,
                region_match, source_release_id
            ) VALUES (
                :software_id, :kind, :media_id, :basis,
                :region_match, :source_release_id
            )
        """)
        with self.engine.begin() as connection:
            connection.execute(ddl)
            asset_rows = [
                {
                    "kind": asset.kind,
                    "directory": asset.directory,
                    "file_name": asset.file_name,
                    "path": asset.relative_path,
                }
                for asset in assets.values()
            ]
            for offset in range(0, len(asset_rows), 5_000):
                connection.execute(insert_media, asset_rows[offset:offset + 5_000])
            media_ids = {
                relative_path: media_id
                for relative_path, media_id in connection.execute(text(
                    "SELECT relative_path, id FROM catalog.media"
                ))
            }
            association_rows = [
                {
                    "software_id": software_id,
                    "kind": kind,
                    "media_id": media_ids[choice.asset.relative_path],
                    "basis": choice.basis,
                    "region_match": choice.region_match,
                    "source_release_id": choice.source_release_id,
                }
                for (software_id, kind), choice in choices.items()
            ]
            for offset in range(0, len(association_rows), 5_000):
                connection.execute(
                    insert_association,
                    association_rows[offset:offset + 5_000],
                )
            stored_assets = connection.scalar(text(
                "SELECT count(*) FROM catalog.media"
            ))
            stored_associations = connection.scalar(text(
                "SELECT count(*) FROM catalog.software_media"
            ))
            invalid_sources = connection.scalar(text("""
                SELECT count(*)
                FROM catalog.software_media selected
                LEFT JOIN catalog.software_release membership
                  ON membership.software_id = selected.software_id
                 AND membership.release_id = selected.source_release_id
                WHERE selected.source_release_id IS NOT NULL
                  AND membership.release_id IS NULL
            """))
            if stored_assets != len(assets):
                raise RuntimeError("Media asset count changed during publication")
            if stored_associations != len(choices):
                raise RuntimeError("Software media count changed during publication")
            if invalid_sources:
                raise RuntimeError(
                    f"{invalid_sources} media associations cite another software's release"
                )
            connection.execute(text("""
                CREATE INDEX software_media_media_idx
                    ON catalog.software_media(media_id);
                CREATE INDEX media_kind_idx ON catalog.media(media_kind);
                ANALYZE catalog.media;
                ANALYZE catalog.software_media;
            """))
