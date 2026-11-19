"""Database boundary for catalog exploration and working corrections."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from gamedb.config import PROJECT_ROOT
from gamedb.explorer.cache import JsonResponseCache


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


def with_source_facts(native, fields, source_list, revision):
    """Keep existing selections and attribute direct, edition-scoped eXo claims."""
    groups = {fact["key"]: dict(fact) for fact in native}
    for name, values in (fields or {}).items():
        if not values:
            continue
        group = groups.setdefault(name, {"key": name, "preferredValues": list(values), "values": []})
        claims = list(group["values"])
        rank = max((claim["rank"] for claim in claims), default=0) + 1
        for value in values:
            claims.append({"value": value, "rank": rank, "selected": value in group["preferredValues"],
                "sourceProvider": "exo", "sourceDatabases": [source_list], "sourceRevision": revision,
                "sourceRecordCount": 1, "matchedContentCount": 0, "candidateCount": len(values)})
        group["values"] = claims
    return list(groups.values())


def preferred_view(hide_rom_hacks: bool) -> str:
    return "app.user_preferred_release_without_hacks" if hide_rom_hacks else "app.user_preferred_release"


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
    ) -> str:
        return SqlTemplate(QUERY_DIRECTORY / "titles.sql").render(
            software_scope=self.software_scope_sql(system_id, title_filter, metadata_filters, hide_rom_hacks),
            limit=sql_integer(limit, "limit", 1),
            offset=sql_integer(offset, "offset"),
        )

    def software_scope_sql(
        self, system_id: int | None, title_filter: str = "",
        metadata_filters: dict | None = None, hide_rom_hacks: bool = False,
    ) -> str:
        predicates = []
        exo_predicates = []
        for key, values in validate_metadata_filters(metadata_filters).items():
            literals = ", ".join(quote_sql_text(value) for value in values)
            digests = ", ".join(f"md5({quote_sql_text(value)})" for value in values)
            exo_facts = f"(entry.facts -> {quote_sql_text(key)}) ?| ARRAY[{literals}]"
            exo_predicates.append(f"AND ({exo_facts})")
            predicates.append(f"""AND (EXISTS (
                SELECT 1 FROM catalog.software_fact filter_fact
                WHERE filter_fact.software_id = software.id
                  AND filter_fact.is_selected
                  AND filter_fact.fact_key = {quote_sql_text(key)}
                  AND md5(filter_fact.fact_value) IN ({digests})
                  AND filter_fact.fact_value IN ({literals})
            ) OR {exo_facts})""")
        return SqlTemplate(QUERY_DIRECTORY / "software_scope.sql").render(
            preferred_view=preferred_view(hide_rom_hacks),
            username=quote_sql_text(self.username),
            system_id="NULL" if system_id is None else sql_integer(system_id, "system_id", 1),
            title_filter=quote_sql_text(title_filter),
            metadata_predicates="\n".join(predicates), exo_predicates="\n".join(exo_predicates),
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

    def install_manifest_sql(self, release_signature: str) -> str:
        return SqlTemplate(QUERY_DIRECTORY / "install_manifest.sql").render(
            username=quote_sql_text(self.username),
            release_signature=quote_sql_text(
                self._signature(release_signature, "release_signature")
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
                item.get("sourceList"), item.get("sourceRevision"),
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

    def exo_detail(self, key):
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("Invalid source work key")
        return self._read_listing(SqlTemplate(QUERY_DIRECTORY / "exo_detail.sql").render(
            work_key=quote_sql_text(key)))

    def exo_asset(self, key):
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("Invalid source asset key")
        return self._read_listing(SqlTemplate(QUERY_DIRECTORY / "exo_location.sql").render(
            asset_key=quote_sql_text(key)))

    def launchbox_image(self, relative_path):
        return self.client.query("""
            SELECT jsonb_build_object('fileName',file_name,'crc32',source_crc32)
            FROM catalog.media WHERE provider='launchbox' AND relative_path=
        """ + quote_sql_text(relative_path) + " LIMIT 1")

    def software_facts(self, software_id: int):
        native = self.client.query(self.software_facts_sql(software_id))
        source = self._read_listing("""
            SELECT jsonb_build_array(e.facts,e.source_list,p.source_revision)
            FROM catalog.exo_browse b JOIN catalog.exo_entry e USING(entry_key)
            CROSS JOIN catalog.exo_publication p WHERE b.software_id=""" + str(sql_integer(software_id,"software_id",1)) +
            " ORDER BY b.scope_id LIMIT 1")
        return with_source_facts(native, *source) if source else native

    def system_software_facts(self, system_id: int):
        payload = self._read_listing(self.system_software_facts_sql(system_id))
        return payload if isinstance(payload, dict) else {}

    def arcade_install_manifest(self, release_signature: str):
        return self.client.query(SqlTemplate(QUERY_DIRECTORY / "arcade_install_manifest.sql").render(
            release_signature=quote_sql_text(self._signature(release_signature, "release_signature"))
        ))

    def install_manifest(self, release_signature: str):
        return self.client.query(self.install_manifest_sql(release_signature))

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
