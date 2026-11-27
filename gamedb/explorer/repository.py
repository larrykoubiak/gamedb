"""Database boundary for catalog exploration and working corrections."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from gamedb.catalog.cartridges import verified_roms_sql
from gamedb.catalog.neogeo import PLATFORM as NEOGEO, SET_NAME as NEOGEO_SET, add_arcade_sets, arcade_sets_sql
from gamedb.catalog.disc_catalog import DISC_ADDON_PARENTS, DISC_SYSTEMS
from gamedb.catalog.retail import RETAIL_PLATFORMS, retail_tables
from gamedb.catalog.software_identity import SOFTWARE_KEY_SQL
from gamedb.config import PROJECT_ROOT
from gamedb.explorer.cache import JsonResponseCache
from gamedb.explorer.retail_metadata import add_release_metadata
from gamedb.explorer.soundtrack_audio import flac_formats
from gamedb.vgm.joshw import (
    COLLECTION as JOSHW_COLLECTION, prefer_playstation_sources, superseded_sources, supports_version, title_revision,
)


QUERY_DIRECTORY = PROJECT_ROOT / "sql" / "queries" / "explorer"
UNRESOLVED_TOKEN = re.compile(r"__[A-Z][A-Z0-9_]*__")
CONTENT_SIGNATURE = re.compile(r"[0-9a-f]{32}")
METADATA_FILTER_KEYS = frozenset({
    "developer", "publisher", "genre", "franchise", "player_count",
    "enhancement_hardware", "rumble", "analog", "origin", "tags",
})


def validate_metadata_filters(filters: dict | None) -> dict[str, list[str]]:
    if filters is None:
        return {}
    if not isinstance(filters, dict) or filters.keys() - METADATA_FILTER_KEYS:
        raise ValueError("Unknown metadata filter")
    result = {}
    for key, values in filters.items():
        if (not isinstance(values, list) or len(values) > 25
                or any(not isinstance(value, str) or not value or len(value) > 1000
                       for value in values)):
            raise ValueError("Metadata filters require up to 25 nonempty text values per field")
        if values:
            result[key] = sorted(set(values))
    return dict(sorted(result.items()))


def quote_sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def with_source_facts(native, fields, source_list, revision, prefer_source=False):
    """Choose values from the preferred edition and retain the other provider's claims."""
    groups = {fact["key"]: dict(fact) for fact in native}
    for name, values in (fields or {}).items():
        if not values:
            continue
        group = groups.setdefault(name, {"key": name, "preferredValues": list(values), "values": []})
        claims = list(group["values"])
        if prefer_source:
            group["preferredValues"] = list(values)
            claims = [
                {**claim, "rank": claim["rank"] + 1, "selected": claim["value"] in values}
                for claim in claims
            ]
            rank = 1
        else:
            rank = max((claim["rank"] for claim in claims), default=0) + 1
        for value in values:
            claims.append({"value": value, "rank": rank, "selected": value in group["preferredValues"],
                "sourceProvider": "exo", "sourceDatabases": [source_list], "sourceRevision": revision,
                "sourceRecordCount": 1, "matchedContentCount": 0, "sourceScore": 0,
                "candidateCount": len(values)})
        group["values"] = sorted(claims, key=lambda claim: claim["rank"])
    return list(groups.values())


def preferred_view(hide_rom_hacks: bool) -> str:
    return "app.user_preferred_release_without_hacks" if hide_rom_hacks else "app.user_preferred_release"


def select_soundtracks(platform, release_versions, albums):
    """Keep corrected copies and select music for the preferred release when available."""
    available = [album for album in albums if album["assets"]]
    superseded = superseded_sources(album["sourceName"] for album in available
                                    if album["collection"] == JOSHW_COLLECTION)
    available = [album for album in available if album["collection"] != JOSHW_COLLECTION
                 or album["sourceName"] not in superseded]
    available = prefer_playstation_sources(available)
    matching = []
    for album in available:
        _, version = title_revision(album["title"])
        if version and supports_version(platform, version, release_versions):
            matching.append(album)
    return [{field: album[field] for field in ("title", "collection", "assets")} for album in matching or available]


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
        bindings = {f"__{name.upper()}__": str(value) for name, value in values.items()}
        unresolved = sorted(set(UNRESOLVED_TOKEN.findall(sql)) - bindings.keys())
        if unresolved:
            raise ValueError(
                f"Unbound SQL token(s) in {self.path.name}: {', '.join(unresolved)}"
            )
        # Substitute only tokens from the template itself. Literal user text
        # and already-rendered SQL fragments must never be reinterpreted.
        return UNRESOLVED_TOKEN.sub(lambda match: bindings[match.group()], sql)


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


class CatalogChanged(Exception):
    """A publication committed while a listing was being assembled."""


class CatalogRepository:
    """Provide catalog reads and validated working-correction writes."""

    def __init__(self, username: str, client: PsqlJsonClient | None = None, *, listing_engine=None):
        self.username = username
        self.client = client or PsqlJsonClient()
        self.listing_engine = listing_engine
        self.listing_cache = JsonResponseCache(max_entries=512, max_bytes=64 * 1024 * 1024, ttl=None)

    def systems_sql(self, hide_rom_hacks=False) -> str:
        return SqlTemplate(QUERY_DIRECTORY / "systems.sql").render(
            username=quote_sql_text(self.username), preferred_view=preferred_view(hide_rom_hacks),
            hide_mods="true" if hide_rom_hacks else "false",
        )

    def catalog_revision_sql(self) -> str:
        return SqlTemplate(QUERY_DIRECTORY / "catalog_revision.sql").render(
            username=quote_sql_text(self.username)
        )

    def titles_sql(
        self, system_id: int | None, limit: int, offset: int, title_filter: str = "",
        metadata_filters: dict | None = None, hide_rom_hacks: bool = False,
        *, software_id: int | None = None, work_key: str | None = None,
    ) -> str:
        return SqlTemplate(QUERY_DIRECTORY / "titles.sql").render(
            software_scope=self.software_scope_sql(
                system_id, title_filter, metadata_filters, hide_rom_hacks,
                software_id=software_id, work_key=work_key,
            ),
            software_key_sql=SOFTWARE_KEY_SQL,
            limit=sql_integer(limit, "limit", 1),
            offset=sql_integer(offset, "offset"),
        )

    def software_scope_sql(
        self, system_id: int | None, title_filter: str = "",
        metadata_filters: dict | None = None, hide_rom_hacks: bool = False,
        *, software_id: int | None = None, work_key: str | None = None,
    ) -> str:
        native_selection = source_selection = ""
        if software_id is not None:
            ident = sql_integer(software_id, "software_id", 1)
            native_selection, source_selection = f"AND software.id = {ident}", f"AND exo.software_id = {ident}"
        elif work_key is not None:
            native_selection = source_selection = f"AND exo.work_key = {quote_sql_text(work_key)}"
        predicates = []
        exo_predicates = []
        for key, values in validate_metadata_filters(metadata_filters).items():
            literals = ", ".join(quote_sql_text(value) for value in values)
            digests = ", ".join(f"md5({quote_sql_text(value)})" for value in values)
            exo_facts = f"(entry.facts -> {quote_sql_text(key)}) ?| ARRAY[{literals}]"
            exo_predicates.append(f"AND ({exo_facts})")
            native_values = f"""SELECT 1 FROM catalog.software_fact filter_fact
                WHERE filter_fact.software_id = software.id AND filter_fact.is_selected
                  AND filter_fact.fact_key = {quote_sql_text(key)}"""
            predicates.append(f"""AND (CASE
                WHEN choice.score > preferred.score AND entry.facts ? {quote_sql_text(key)}
                    THEN {exo_facts}
                ELSE EXISTS (
                  {native_values}
                  AND md5(filter_fact.fact_value) IN ({digests})
                  AND filter_fact.fact_value IN ({literals})
                ) OR ({exo_facts} AND NOT EXISTS ({native_values}))
            END)""")
        return SqlTemplate(QUERY_DIRECTORY / "software_scope.sql").render(
            preferred_view=preferred_view(hide_rom_hacks),
            username=quote_sql_text(self.username),
            system_id="NULL" if system_id is None else sql_integer(system_id, "system_id", 1),
            title_filter=quote_sql_text(title_filter),
            metadata_predicates="\n".join(predicates), exo_predicates="\n".join(exo_predicates),
            native_selection=native_selection, source_selection=source_selection,
            hide_mods="true" if hide_rom_hacks else "false",
        )

    def metadata_options_sql(
        self, key: str, system_id: int | None = None, title_filter: str = "",
        metadata_filters: dict | None = None, search: str = "", hide_rom_hacks: bool = False,
    ) -> str:
        if key not in METADATA_FILTER_KEYS:
            raise ValueError("Unknown metadata field")
        filters = validate_metadata_filters(metadata_filters)
        filters.pop(key, None)
        return SqlTemplate(QUERY_DIRECTORY / "metadata_options.sql").render(
            software_scope=self.software_scope_sql(system_id, title_filter, filters, hide_rom_hacks),
            fact_key=quote_sql_text(key),
            option_search=quote_sql_text(search[:100]),
        )

    def software_releases_sql(self, software_id: int, hide_rom_hacks=False) -> str:
        return SqlTemplate(QUERY_DIRECTORY / "title_releases.sql").render(
            preferred_view=preferred_view(hide_rom_hacks),
            username=quote_sql_text(self.username),
            software_id=sql_integer(software_id, "software_id", 1),
        )

    def software_facts_sql(self, software_id: int) -> str:
        return SqlTemplate(QUERY_DIRECTORY / "software_facts.sql").render(
            software_id=sql_integer(software_id, "software_id", 1),
        )

    def system_software_facts_sql(self, system_id: int) -> str:
        return SqlTemplate(
            QUERY_DIRECTORY / "system_software_facts.sql"
        ).render(system_id=sql_integer(system_id, "system_id", 1))

    def install_manifest_sql(self, release_signature: str, retail_platforms=(), *, software_key=None) -> str:
        published = " UNION ALL ".join(
            f"SELECT payload FROM {retail_tables(platform)[0]} WHERE singleton"
            for platform in retail_platforms
        )
        return SqlTemplate(QUERY_DIRECTORY / "install_manifest.sql").render(
            username=quote_sql_text(self.username),
            release_signature=quote_sql_text(
                self._signature(release_signature, "release_signature")
            ),
            software_key="NULL" if software_key is None else quote_sql_text(self._signature(software_key, "software_key")),
            retail_catalogs_sql=published or "SELECT NULL::jsonb AS payload WHERE false",
            retail_install_releases_sql=self._retail_install_releases_sql(
                "SELECT link_no, archive FROM retail_links", signature_source="inventory",
            ),
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

    def _read_listing(self, sql):
        if self.listing_engine is None:
            return self.client.query(sql)
        with self.listing_engine.connect() as connection:
            # Templates already contain quoted literals. A '%' in a game title
            # or search must reach PostgreSQL unchanged.
            result = connection.exec_driver_sql(sql, execution_options={"no_parameters": True})
            return result.scalar_one_or_none()

    def _published_revision(self):
        payload = self._read_listing(self.catalog_revision_sql())
        return payload.get("catalogRevision") if isinstance(payload, dict) else None

    def catalog_revision(self) -> str:
        revision = self._published_revision()
        if not revision:
            raise ValueError(f"No scoring generation exists for user {self.username!r}")
        return revision

    def load_at_revision(self, revision, loader):
        payload = loader()
        if self._published_revision() != revision:
            raise CatalogChanged()
        return payload

    def _listing_query(self, sql, revision=None):
        revision = revision or self._published_revision()
        if not revision:
            return self._read_listing(sql)
        return self.listing_cache.get_or_load(
            revision + "\n" + sql,
            lambda: self.load_at_revision(revision, lambda: self._read_listing(sql)),
        )

    def systems(self, revision=None, hide_rom_hacks=False):
        return self._listing_query(self.systems_sql(hide_rom_hacks), revision)

    def retail_available(self, platform):
        table, _, _ = retail_tables(platform)
        return self._read_listing(f"SELECT to_jsonb(to_regclass('{table}') IS NOT NULL)")

    def published_retail_platforms(self):
        tables = ", ".join(f"('{platform}', '{retail_tables(platform)[0]}')" for platform in RETAIL_PLATFORMS)
        return self._read_listing(f"""
            SELECT coalesce(jsonb_agg(platform ORDER BY platform), '[]'::jsonb)
            FROM (VALUES {tables}) AS retail(platform, relation)
            WHERE to_regclass(relation) IS NOT NULL
        """)

    def retail_has_archive(self, platform, signature):
        if not self.retail_available(platform):
            return False
        table, _, _ = retail_tables(platform)
        return self._read_listing(f"""
            SELECT to_jsonb(EXISTS (
                SELECT FROM {table}
                WHERE singleton AND jsonb_path_exists(
                    payload,
                    '$.games[*].releases[*] ? (@.status == "matched").archives[*] ? (@.signature == $signature)',
                    jsonb_build_object('signature', {quote_sql_text(signature)}::text)
                )
            ))
        """)

    def retail_translation_base(self, platform, signature, sha1):
        """Locate the exact official revision linked to a translation."""
        if not self.retail_available(platform):
            return None
        table, _, _ = retail_tables(platform)
        base = verified_roms_sql(f"ARRAY[{quote_sql_text(signature)}]")
        return self._read_listing(f"""
            SELECT to_jsonb(base)
            FROM ({base}) AS base
            WHERE base.sha1 = {quote_sql_text(sha1)} AND EXISTS (
                SELECT 1 FROM {table}
                WHERE singleton AND jsonb_path_exists(
                    payload,
                    '$.games[*].releases[*] ? (@.status == "matched").archives[*] ? (@.signature == $signature)',
                    jsonb_build_object('signature', base.signature)
                )
            )
        """)

    def retail_catalog(self, platform, *, game_key=None, browse=False):
        if game_key is not None and not CONTENT_SIGNATURE.fullmatch(game_key):
            raise ValueError("Invalid retail catalog key")
        if not self.retail_available(platform):
            return None
        table, _, _ = retail_tables(platform)
        if game_key is not None:
            key = quote_sql_text(game_key)
            catalog = self._read_listing(f"""
                SELECT jsonb_build_object('source', payload->'source', 'addonSources', payload->'addonSources',
                    'releaseSources', payload->'releaseSources', 'game', game)
                FROM {table}
                CROSS JOIN LATERAL jsonb_array_elements(payload->'games') AS games(game)
                WHERE singleton AND (game->>'key' = {key} OR (game->'formerKeys') ? {key})
            """)
            if catalog:
                game = catalog["game"]
                if platform == NEOGEO:
                    names = sorted({name for release in game["releases"] for name in release.get("setNames", ())
                                    if NEOGEO_SET.fullmatch(name)})
                    if names:
                        names_sql = ", ".join(map(quote_sql_text, names))
                        records = self._read_listing(
                            "SELECT coalesce(jsonb_agg(to_jsonb(sets)), '[]'::jsonb) FROM ("
                            + arcade_sets_sql(f"ARRAY[{names_sql}]::text[]") + ") sets"
                        )
                        add_arcade_sets([game], records)
                add_release_metadata(game, self.retail_release_facts(game), snes_peripherals=platform == "snes")
            return catalog
        if browse:
            return self.retail_browse(platform)
        return self._read_listing(f"SELECT payload FROM {table} WHERE singleton")

    def retail_browse(self, platform):
        table, _, _ = retail_tables(platform)
        genres = "SELECT NULL::bigint AS game_order, NULL::jsonb AS items WHERE false"
        if platform != NEOGEO and self._retail_facts_available():
            verified = self._retail_verified_releases_sql("""
                SELECT release->>'key' AS release_key, (archive->>'softwareId')::bigint AS software_id,
                    archive->>'softwareKey' AS software_key, archive->>'signature' AS signature
                FROM releases
                CROSS JOIN LATERAL jsonb_array_elements(release->'archives') AS a(archive)
                WHERE release->>'status' = 'matched'
            """)
            genres = f"""
                SELECT releases.game_order, jsonb_agg(DISTINCT fact.fact_value ORDER BY fact.fact_value) AS items
                FROM ({verified}) verified
                JOIN releases ON releases.release->>'key' = verified.release_key
                JOIN catalog.software_fact fact ON fact.software_id = verified.software_id
                WHERE fact.is_selected AND fact.fact_key = 'genre'
                GROUP BY releases.game_order
            """
        return self._read_listing(SqlTemplate(QUERY_DIRECTORY / "retail_browse.sql").render(
            catalog_table=table, genres_sql=genres,
        ))

    def retail_browse_revision(self, platform):
        table, _, _ = retail_tables(platform)
        relations = self._read_listing(f"""
            SELECT jsonb_build_object(
                'retail', to_regclass('{table}') IS NOT NULL,
                'listings', to_regclass('catalog.listing_generation') IS NOT NULL
            )
        """)
        if not relations["retail"]:
            return None
        listing_revision = (
            "(SELECT revision FROM catalog.listing_generation WHERE singleton)"
            if relations["listings"] else "NULL"
        )
        return self._read_listing(f"""
            SELECT jsonb_build_array(published_at, {listing_revision})
            FROM {table} WHERE singleton
        """)

    def _retail_facts_available(self):
        return self._read_listing("SELECT to_jsonb(to_regclass('catalog.software_fact') IS NOT NULL)")

    def _retail_verified_releases_sql(self, links_sql):
        return SqlTemplate(QUERY_DIRECTORY / "retail_verified_releases.sql").render(
            links_sql=links_sql, software_key_sql=SOFTWARE_KEY_SQL,
        )

    def _retail_install_releases_sql(self, links_sql, *, signature_source="catalog.release_content_signature"):
        return SqlTemplate(QUERY_DIRECTORY / "retail_install_releases.sql").render(
            links_sql=links_sql, signature_source=signature_source, software_key_sql=SOFTWARE_KEY_SQL,
        )

    def retail_install_paths(self, archives):
        if not archives:
            return []
        links = [{key: archive.get(key) for key in ("signature", "softwareKey", "archiveNames")}
                 for archive in archives]
        eligible = self._retail_install_releases_sql(f"""
            SELECT link_no, archive
            FROM jsonb_array_elements({quote_sql_text(json.dumps(links))}::jsonb)
                 WITH ORDINALITY AS published(archive, link_no)
        """)
        return self._read_listing(f"""
            SELECT coalesce(jsonb_agg(jsonb_build_object('linkNo', link_no, 'paths', paths)), '[]'::jsonb)
            FROM ({eligible}) verified
        """)

    def retail_release_facts(self, game):
        links = [{"release_key": release["key"], "software_id": archive["softwareId"],
                  "software_key": archive["softwareKey"], "signature": archive["signature"]}
                 for release in game["releases"] if release["status"] == "matched"
                 for archive in release.get("archives", ())]
        if not links or not self._retail_facts_available():
            return {}
        verified = self._retail_verified_releases_sql(f"""
            SELECT DISTINCT link.*
            FROM jsonb_to_recordset({quote_sql_text(json.dumps(links))}::jsonb) AS link(
                release_key text, software_id bigint, software_key text, signature text
            )
        """)
        return self._read_listing(SqlTemplate(QUERY_DIRECTORY / "retail_release_facts.sql").render(
            verified_releases_sql=verified,
        ))

    def catalog_manifest(self, revision: str | None = None, hide_rom_hacks=False):
        revision = revision or self.catalog_revision()
        return {
            "catalogRevision": revision,
            "systems": self.systems(revision, hide_rom_hacks),
        }

    def system_by_key(self, system_key: str, revision: str, hide_rom_hacks=False):
        if not re.fullmatch(r"[0-9a-f]{32}", system_key):
            raise ValueError("system_key must be a 32-character lowercase hex key")
        return next(
            (item for item in self.systems(revision, hide_rom_hacks) if item.get("key") == system_key),
            None,
        )

    def system_software(self, system_key: str, revision: str | None = None, hide_rom_hacks=False):
        revision = revision or self.catalog_revision()
        system = self.system_by_key(system_key, revision, hide_rom_hacks)
        if system is None:
            return None
        # Cache the complete snapshot at the HTTP boundary. A second copy of
        # all titles for a large system would displace ordinary browse pages.
        catalog = self._read_listing(self.titles_sql(
            int(system["id"]), max(1, int(system["gameCount"])), 0, hide_rom_hacks=hide_rom_hacks,
        ))
        software_facts = self.system_software_facts(int(system["id"])) if catalog["items"] else {}
        items = []
        for source_item in catalog["items"]:
            item = dict(source_item)
            item["softwareFacts"] = with_source_facts(
                software_facts.get(str(item["softwareId"]), []), item.pop("sourceFacts", None),
                item.get("sourceList"), item.get("sourceRevision"), bool(item.get("preferredEditionKey")),
            )
            items.append(item)
        return {
            "catalogRevision": revision,
            "system": {
                "key": system["key"],
                "manufacturer": system["manufacturer"],
                "name": system["name"],
                "softwareCount": system["gameCount"],
            },
            "items": items,
        }

    def titles(
        self, system_id: int | None, limit: int, offset: int, title_filter: str = "",
        metadata_filters: dict | None = None, hide_rom_hacks: bool = False,
    ):
        return self._listing_query(
            self.titles_sql(system_id, limit, offset, title_filter, metadata_filters, hide_rom_hacks)
        )

    def metadata_options(self, key, system_id=None, title_filter="", metadata_filters=None, search="", hide_rom_hacks=False):
        sql = self.metadata_options_sql(
            key, system_id, title_filter, metadata_filters, search, hide_rom_hacks
        )
        return self._listing_query(sql)

    def software_releases(self, software_id: int, hide_rom_hacks=False):
        return self.client.query(self.software_releases_sql(software_id, hide_rom_hacks))

    def _page_listing(self, hide_rom_hacks, *, software_key=None, **selection):
        modes = (True, False) if hide_rom_hacks else (False,)
        for mode in modes:
            payload = self._read_listing(self.titles_sql(None, 16, 0, hide_rom_hacks=mode, **selection))
            items = payload["items"]
            if software_key:
                items = [item for item in items if item.get("softwareKey") == software_key]
            if items:
                game = max(items, key=lambda item: (not item.get("sourceOnly"), item["score"]))
                return {"game": game, "hideRomHacks": mode}
        return None

    def software_page(self, hint, key, hide_rom_hacks=False):
        if not re.fullmatch(r"[0-9a-f]{32}", key):
            raise ValueError("Invalid software key")
        software_id = self._read_listing(SqlTemplate(QUERY_DIRECTORY / "software_lookup.sql").render(
            software_id=sql_integer(hint, "software_id", 1), key=quote_sql_text(key),
            software_key_sql=SOFTWARE_KEY_SQL,
        ))
        if software_id is None:
            return None
        return self._page_listing(hide_rom_hacks, software_id=software_id, software_key=key)

    def exo_page(self, key, hide_rom_hacks=False):
        source = self.exo_detail(key)
        if source is None:
            return None
        page = self._page_listing(hide_rom_hacks, work_key=source["key"])
        if page is None:
            edition = source["editions"][0]
            page = {"game": {
                "title": edition["title"],
                "systemName": edition["system"] or edition["environment"],
                "manufacturer": edition["manufacturer"] or "eXo",
                "sourceOnly": True,
                "sourceDetailKey": source["key"],
                "sourceEntryKey": edition["entryKey"],
            }, "hideRomHacks": False}
        return {**page, "source": source}

    def exo_detail(self, key):
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("Invalid source work key")
        return self._read_listing(SqlTemplate(QUERY_DIRECTORY / "exo_detail.sql").render(
            work_key=quote_sql_text(key),username=quote_sql_text(self.username)))

    def exo_asset(self, key):
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("Invalid source asset key")
        return self._read_listing(SqlTemplate(QUERY_DIRECTORY / "exo_location.sql").render(
            asset_key=quote_sql_text(key)))

    def vgm_soundtracks(self, software_id: int, hide_rom_hacks=False):
        has_additional_targets = self._read_listing("""
            SELECT CASE WHEN to_regclass('vgm.soundtrack') IS NULL THEN 'null'::jsonb
                   ELSE to_jsonb(EXISTS (
                       SELECT FROM pg_attribute WHERE attrelid = to_regclass('vgm.soundtrack')
                       AND attname = 'additional_target_keys' AND NOT attisdropped
                   )) END
        """)
        if has_additional_targets is None:
            return []
        additional_targets = "OR soundtrack.additional_target_keys @> ARRAY[target.key]" if has_additional_targets else ""
        albums_sql = SqlTemplate(QUERY_DIRECTORY / "vgm_albums.sql").render(
            album_filter="soundtrack.target_key = target.key " + additional_targets,
            flac_formats=", ".join(map(quote_sql_text, sorted(flac_formats()))),
        )
        payload = self._read_listing(SqlTemplate(QUERY_DIRECTORY / "vgm_soundtracks.sql").render(
            software_id=sql_integer(software_id, "software_id", 1), software_key_sql=SOFTWARE_KEY_SQL,
            albums_sql=albums_sql, preferred_view=preferred_view(hide_rom_hacks),
            username=quote_sql_text(self.username),
        ))
        return select_soundtracks(tuple(payload["platform"]), payload["releaseVersions"], payload["albums"]) if payload else []

    def retail_soundtracks(self, game):
        links = {link["key"]: link for link in game.get("soundtrackLinks", ())
                 if re.fullmatch(r"[a-f0-9]{64}", link["key"])}
        if not links or not self._read_listing("""
            SELECT to_jsonb(to_regclass('vgm.soundtrack') IS NOT NULL AND to_regclass('vgm.asset') IS NOT NULL)
        """):
            return []
        keys = ", ".join(map(quote_sql_text, links))
        albums = self._read_listing(SqlTemplate(QUERY_DIRECTORY / "vgm_albums.sql").render(
            album_filter=f"soundtrack.key IN ({keys})",
            flac_formats=", ".join(map(quote_sql_text, sorted(flac_formats()))),
        ))
        return prefer_playstation_sources([
            {**album, **{name: links[album["key"]][name] for name in ("releases", "titleMatches", "sourceUrl")
                         if name in links[album["key"]]}}
            for album in albums if album["assets"]
        ])

    def vgm_asset(self, key):
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("Invalid VGM asset key")
        tables = [retail_tables(platform)[2] for platform in RETAIL_PLATFORMS]
        existence = ", ".join(f"to_regclass('{table}') IS NOT NULL" for table in tables)
        present = self._read_listing(f"""
            SELECT CASE WHEN to_regclass('vgm.asset') IS NOT NULL
                        THEN jsonb_build_array({existence}) END
        """)
        if present is None:
            return None
        retail_link = "\n".join(
            f"OR EXISTS (SELECT FROM {table} retail WHERE retail.soundtrack_key = soundtrack.key)"
            for table, exists in zip(tables, present, strict=True) if exists
        )
        return self._read_listing(SqlTemplate(QUERY_DIRECTORY / "vgm_location.sql").render(
            asset_key=quote_sql_text(key), retail_link=retail_link,
        ))

    def launchbox_image(self, relative_path):
        path = quote_sql_text(relative_path)
        tables = [retail_tables(platform)[1] for platform in RETAIL_PLATFORMS]
        existence = ", ".join(f"to_regclass('{table}') IS NOT NULL" for table in tables)
        present = self._read_listing(f"SELECT jsonb_build_array({existence})")
        choices = [f"SELECT jsonb_build_object('fileName',filename,'crc32',crc32) FROM {table} WHERE path = {path}"
                   for table, exists in zip(tables, present, strict=True) if exists]
        if choices:
            asset = self._read_listing(" UNION ALL ".join(choices) + " LIMIT 1")
            if asset:
                return asset
        if not self._read_listing("""
            SELECT to_jsonb(EXISTS (
                SELECT 1 FROM pg_attribute
                WHERE attrelid = to_regclass('catalog.media') AND attname = 'source_crc32' AND NOT attisdropped
            ))
        """):
            return None
        return self._read_listing("""
            SELECT jsonb_build_object('fileName',file_name,'crc32',source_crc32)
            FROM catalog.media WHERE provider='launchbox' AND relative_path =
        """ + path + " LIMIT 1")

    def software_facts(self, software_id: int, hide_rom_hacks=False):
        native = self.client.query(self.software_facts_sql(software_id))
        source = self._read_listing(SqlTemplate(QUERY_DIRECTORY / "exo_software_facts.sql").render(
            preferred_view=preferred_view(hide_rom_hacks), username=quote_sql_text(self.username),
            software_id=sql_integer(software_id, "software_id", 1), hide_mods="true" if hide_rom_hacks else "false",
        ))
        return with_source_facts(native, *source) if source else native

    def system_software_facts(self, system_id: int):
        payload = self._read_listing(self.system_software_facts_sql(system_id))
        return payload if isinstance(payload, dict) else {}

    def arcade_install_manifest(self, release_signature: str):
        return self.client.query(SqlTemplate(QUERY_DIRECTORY / "arcade_install_manifest.sql").render(
            release_signature=quote_sql_text(self._signature(release_signature, "release_signature"))
        ))

    def install_manifest(self, release_signature: str, *, software_key=None):
        platforms = self.published_retail_platforms()
        manifest = self._read_listing(self.install_manifest_sql(release_signature, platforms, software_key=software_key))
        if software_key is not None:
            return manifest
        available = {disc: DISC_ADDON_PARENTS.get(disc, disc) for disc in DISC_SYSTEMS
                     if DISC_ADDON_PARENTS.get(disc, disc) in platforms}
        if manifest is None and available:
            catalogs = []
            for disc, parent in available.items():
                manufacturer, system = DISC_SYSTEMS[disc]
                catalogs.append(
                    f"SELECT payload, {quote_sql_text(manufacturer)} AS manufacturer, {quote_sql_text(system)} AS system_name "
                    f"FROM {retail_tables(parent)[0]} WHERE singleton"
                )
            return self._read_listing(SqlTemplate(QUERY_DIRECTORY / "disc_install_manifest.sql").render(
                release_signature=quote_sql_text(self._signature(release_signature, "release_signature")),
                catalogs_sql=" UNION ALL ".join(catalogs),
            ))
        return manifest

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
