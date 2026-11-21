"""Local HTTP transport and static assets for catalog exploration."""

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import threading
from urllib.parse import parse_qs, quote, unquote, urlparse

from sqlalchemy.exc import SQLAlchemyError

from gamedb.arcade.bundle import prepare_manifest, public_manifest, write_bundle
from gamedb.config import PROJECT_ROOT, ProjectEnvironment
from gamedb.database import create_database_engine
from gamedb.explorer.cache import JsonResponseCache
from gamedb.explorer.previews import ArtworkPreviewCache
from gamedb.explorer.related_media import serve as serve_related_media, serve_vgm
from gamedb.explorer.repository import CatalogChanged, CatalogRepository, validate_metadata_filters
from gamedb.launchbox.image_cache import LaunchBoxImageCache, valid_filename


ASSET_DIRECTORY = Path(__file__).with_name("assets")
PROJECT_ENV = Path(__file__).resolve().parent.parent / ".env"
USERNAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")
SYSTEM_TITLES = re.compile(r"/api/systems/([0-9]+)/titles")
SOFTWARE_RELEASES = re.compile(r"/api/software/([0-9]+)/releases")
SOFTWARE_VGM = re.compile(r"/api/(?:v1/)?software/([0-9]+)/soundtracks")
SOFTWARE_FACTS = re.compile(r"/api/software/([0-9]+)/facts")
SOFTWARE_PAGE = re.compile(r"/software/(?:([1-9][0-9]{0,18})-([0-9a-f]{32})|exo/([0-9a-f]{64}))")
INSTALL_MANIFEST = re.compile(r"/api/v1/releases/([0-9a-f]{32})/install-manifest")
INSTALL_BUNDLE = re.compile(r"/api/v1/releases/([0-9a-f]{32})/install-bundle")
PACKAGE_DOWNLOAD = re.compile(
    r"/api/v1/releases/([0-9a-f]{32})/packages/([0-9a-f]{32})/download"
)
CORRECTION_TARGETS = re.compile(r"/api/systems/([0-9]+)/correction-targets")
SYSTEM_SOFTWARE_SNAPSHOT = re.compile(
    r"/api/v1/systems/([0-9a-f]{32})/software"
)
PAGE_SIZE_MAXIMUM = 200
DEFAULT_PORT = 8000
MEDIA_PREFIX = "/media/"
PREVIEW_PATH = re.compile(r"/previews/(128|320)/(.+)")
MEDIA_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})
STREAM_CHUNK_SIZE = 1024 * 1024
VGM_DECODER_PREFIX = "/vgm/zxtune-f59403a/"
VGM_STATIC_TYPES = {
    "/vgm/player.js": "text/javascript; charset=utf-8",
    "/vgm/decoder.mjs": "text/javascript; charset=utf-8",
    "/vgm/credits.txt": "text/plain; charset=utf-8",
    VGM_DECODER_PREFIX + "zxtune.mjs": "text/javascript; charset=utf-8",
    VGM_DECODER_PREFIX + "zxtune.wasm": "application/wasm",
    VGM_DECODER_PREFIX + "licenses.txt": "text/plain; charset=utf-8",
}


def _metadata_filters(query):
    raw = query.get("filters", ["{}"])[0]
    if len(raw) > 16000:
        raise ValueError("Metadata filters are too large")
    return validate_metadata_filters(json.loads(raw))


def _hide_rom_hacks(query):
    values = query.get("hide_rom_hacks", ["0"])
    if values not in (["0"], ["1"]):
        raise ValueError("hide_rom_hacks must be 0 or 1")
    return values == ["1"]


def _load_project_environment(path: Path = PROJECT_ENV) -> tuple[str, ...]:
    return ProjectEnvironment(path).load()


def _resolve_explorer_port(command_line_port: int | None) -> int:
    if command_line_port is not None:
        return command_line_port
    value = os.environ.get("GAMEDB_EXPLORER_PORT", str(DEFAULT_PORT))
    try:
        return int(value)
    except ValueError as error:
        raise SystemExit("GAMEDB_EXPLORER_PORT must be an integer") from error


def _corrections_enabled() -> bool:
    return os.environ.get("GAMEDB_ENABLE_CORRECTIONS", "").lower() in (
        "1", "true", "yes",
    )


def _api_key() -> str:
    value = os.environ.get("GAMEDB_API_KEY", "").strip()
    if len(value) < 32:
        raise SystemExit("GAMEDB_API_KEY must contain at least 32 characters")
    return value


def _api_authorized(authorization: str | None, api_key: str) -> bool:
    scheme, separator, credential = (authorization or "").partition(" ")
    return (
        bool(separator)
        and scheme.lower() == "bearer"
        and hmac.compare_digest(credential, api_key)
    )


def _request_client(forwarded: str | None, fallback: str) -> str:
    candidate = (forwarded or "").split(",", 1)[0].strip()
    try:
        return str(ipaddress.ip_address(candidate)) if candidate else fallback
    except ValueError:
        return fallback


def _resolve_media_path(root: Path, encoded_path: str) -> Path:
    """Resolve one URL path below the configured thumbnail checkout."""
    decoded = unquote(encoded_path)
    if not decoded or "\x00" in decoded:
        raise ValueError("Invalid media path")
    resolved_root = root.resolve()
    candidate = (resolved_root / decoded).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("Invalid media path") from error
    if candidate.suffix.lower() not in MEDIA_EXTENSIONS:
        raise ValueError("Unsupported media type")
    return candidate


def _resolve_rom_path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("Invalid package path")
    resolved_root = root.resolve()
    candidate = Path(value).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("Package is outside the configured ROM root") from error
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _byte_range(value: str | None, size: int) -> tuple[int, int] | None:
    """Parse one RFC 7233 byte range; multiple ranges are intentionally unsupported."""
    if not value:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if not match or (not match.group(1) and not match.group(2)):
        raise ValueError("Invalid Range header")
    if match.group(1):
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else size - 1
        if start >= size or end < start:
            raise ValueError("Unsatisfiable Range header")
        return start, min(end, size - 1)
    suffix = int(match.group(2))
    if suffix <= 0:
        raise ValueError("Unsatisfiable Range header")
    return max(0, size - suffix), size - 1


def _database_error(stderr: str) -> str:
    if "connection to server" in stderr:
        return "Database connection failed. Check the project .env and that PostgreSQL is running."
    return stderr.strip().splitlines()[-1] if stderr else "Database query failed"


class ExplorerHandler(BaseHTTPRequestHandler):
    """Translate HTTP requests into catalog and correction operations."""

    server_version = "GameDBExplorer/1"

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        for _ in range(2):
            try:
                return self._get()
            except CatalogChanged:
                continue
        return self._json_response(
            {"error": "The catalog is being refreshed. Retry the request."},
            HTTPStatus.SERVICE_UNAVAILABLE,
        )

    def _get(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/v1/") and not _api_authorized(
                self.headers.get("Authorization"), self.server.api_key
            ):
                return self._unauthorized_response()
            query = parse_qs(parsed.query)
            if parsed.path.startswith("/api/") and (page := SOFTWARE_PAGE.fullmatch(parsed.path[4:])):
                repository = self.server.repository
                hide_hacks = _hide_rom_hacks(query)
                detail = (
                    repository.exo_page(page[3], hide_hacks) if page[3]
                    else repository.software_page(int(page[1]), page[2], hide_hacks)
                )
                if detail is None:
                    return self._json_response({"error": "Software entry not found."}, HTTPStatus.NOT_FOUND)
                return self._json_response(detail)
            source = re.fullmatch(r"/api/(?:v1/)?exo/([0-9a-f]{64})", parsed.path)
            if source:
                detail = self.server.repository.exo_detail(source[1])
                if detail is None:
                    return self.send_error(HTTPStatus.NOT_FOUND)
                return self._json_response(detail)
            vgm_asset = re.fullmatch(r"/related-media/vgm/([0-9a-f]{64})", parsed.path)
            if vgm_asset:
                return serve_vgm(self, vgm_asset[1])
            soundtrack = SOFTWARE_VGM.fullmatch(parsed.path)
            if soundtrack:
                items = self.server.repository.vgm_soundtracks(int(soundtrack[1])) if self.server.vgm_root else []
                return self._json_response(items)
            attachment = re.fullmatch(r"/related-media/([0-9a-f]{64})", parsed.path)
            if attachment:
                return serve_related_media(self, attachment[1])
            if parsed.path == "/api/systems":
                return self._json_response(self.server.repository.systems(hide_rom_hacks=_hide_rom_hacks(query)))
            if parsed.path == "/api/capabilities":
                return self._json_response({
                    "softwareCorrections": self.server.corrections_enabled,
                    "vgm": bool(self.server.vgm_root),
                })
            if parsed.path == "/api/metadata-options":
                system_id = query.get("system_id", [""])[0]
                return self._json_response(self.server.repository.metadata_options(
                    query.get("key", [""])[0],
                    int(system_id) if system_id else None,
                    query.get("q", [""])[0].strip()[:100],
                    _metadata_filters(query),
                    query.get("search", [""])[0].strip()[:100],
                    _hide_rom_hacks(query),
                ))
            if parsed.path == "/api/v1/catalog":
                return self._catalog_response(hide_rom_hacks=_hide_rom_hacks(query))
            if parsed.path.startswith(MEDIA_PREFIX):
                return self._media_response(parsed.path[len(MEDIA_PREFIX):])
            preview = PREVIEW_PATH.fullmatch(parsed.path)
            if preview:
                return self._media_response(preview[2], int(preview[1]))

            match = INSTALL_MANIFEST.fullmatch(parsed.path)
            if match:
                return self._install_manifest_response(match.group(1))

            match = INSTALL_BUNDLE.fullmatch(parsed.path)
            if match:
                return self._install_bundle_response(match.group(1))

            match = PACKAGE_DOWNLOAD.fullmatch(parsed.path)
            if match:
                return self._package_response(match.group(1), match.group(2))

            match = SYSTEM_TITLES.fullmatch(parsed.path)
            if match or parsed.path == "/api/titles":
                page = max(1, int(query.get("page", ["1"])[0]))
                page_size = min(
                    PAGE_SIZE_MAXIMUM,
                    max(1, int(query.get("page_size", ["100"])[0])),
                )
                title_filter = query.get("q", [""])[0].strip()[:100]
                payload = self.server.repository.titles(
                    int(match.group(1)) if match else None,
                    page_size,
                    (page - 1) * page_size,
                    title_filter,
                    _metadata_filters(query),
                    _hide_rom_hacks(query),
                )
                payload["page"] = page
                payload["pageSize"] = page_size
                return self._json_response(payload)

            match = SYSTEM_SOFTWARE_SNAPSHOT.fullmatch(parsed.path)
            if match:
                return self._catalog_response(match.group(1), _hide_rom_hacks(query))

            match = SOFTWARE_RELEASES.fullmatch(parsed.path)
            if match:
                return self._json_response(
                    self.server.repository.software_releases(int(match.group(1)), _hide_rom_hacks(query))
                )

            match = SOFTWARE_FACTS.fullmatch(parsed.path)
            if match:
                return self._json_response(
                    self.server.repository.software_facts(int(match.group(1)), _hide_rom_hacks(query))
                )

            match = CORRECTION_TARGETS.fullmatch(parsed.path)
            if match:
                if not self.server.corrections_enabled:
                    return self._json_response(
                        {"error": "Software corrections are disabled"},
                        HTTPStatus.FORBIDDEN,
                    )
                software_id = int(query.get("exclude_software_id", ["0"])[0])
                title_filter = query.get("q", [""])[0].strip()[:100]
                return self._json_response(self.server.repository.correction_targets(
                    int(match.group(1)), software_id, title_filter
                ))

            if parsed.path in ("/", "/index.html"):
                source_key = query.get("exo", [""])[0]
                if re.fullmatch(r"[0-9a-f]{64}", source_key):
                    self.send_response(HTTPStatus.FOUND)
                    self.send_header("Location", f"/software/exo/{source_key}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                return self._asset_response("index.html", "text/html; charset=utf-8")
            if SOFTWARE_PAGE.fullmatch(parsed.path):
                return self._asset_response("index.html", "text/html; charset=utf-8")
            if parsed.path in ("/app.js", "/almanac.js"):
                return self._asset_response(parsed.path[1:], "text/javascript; charset=utf-8")
            if content_type := VGM_STATIC_TYPES.get(parsed.path):
                cache = (
                    "public, max-age=31536000, immutable"
                    if parsed.path.startswith(VGM_DECODER_PREFIX) else "no-store"
                )
                return self._asset_response(parsed.path[1:], content_type, cache)
            if parsed.path == "/system-icons.json":
                return self._asset_response("system-icons.json", "application/json; charset=utf-8")
            if parsed.path == "/system-icon-credits.txt":
                return self._asset_response("system-icon-credits.txt", "text/plain; charset=utf-8")
            icon = re.fullmatch(r"/system-icons/([a-z0-9-]+\.png)", parsed.path)
            if icon:
                asset = f"system-icons/{icon.group(1)}"
                if not (ASSET_DIRECTORY / asset).is_file():
                    return self.send_error(HTTPStatus.NOT_FOUND)
                return self._asset_response(asset, "image/png", "public, max-age=3600")
            if parsed.path in ("/styles.css", "/almanac.css"):
                return self._asset_response(parsed.path[1:], "text/css; charset=utf-8")
            self.send_error(HTTPStatus.NOT_FOUND)
        except (ValueError, TypeError):
            self._json_response(
                {"error": "Invalid request parameters"}, HTTPStatus.BAD_REQUEST
            )
        except SQLAlchemyError as error:
            message = _database_error(str(getattr(error, "orig", error)))
            self._json_response({"error": message}, HTTPStatus.INTERNAL_SERVER_ERROR)
        except subprocess.CalledProcessError as error:
            self._json_response(
                {"error": _database_error(error.stderr or error.stdout)},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path != "/api/software-corrections":
            return self.send_error(HTTPStatus.NOT_FOUND)
        if not self.server.corrections_enabled:
            return self._json_response(
                {"error": "Software corrections are disabled"},
                HTTPStatus.FORBIDDEN,
            )
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 16_384:
                raise ValueError("Invalid request body")
            payload = json.loads(self.rfile.read(length))
            result = self.server.repository.create_correction(
                int(payload["systemId"]), payload["subjectContentSignature"],
                payload["action"], payload.get("targetContentSignature"),
                payload.get("note", ""),
            )
            if not result or not result.get("created"):
                return self._json_response(
                    {"error": "The correction signatures could not be resolved"},
                    HTTPStatus.BAD_REQUEST,
                )
            correction_id = int(result["correctionId"])
            try:
                with self.server.rebuild_lock:
                    self.server.rebuild_software()
            except subprocess.CalledProcessError:
                self.server.repository.disable_correction(correction_id)
                raise
            return self._json_response(result, HTTPStatus.CREATED)
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as error:
            self._json_response(
                {"error": str(error) or "Invalid correction"},
                HTTPStatus.BAD_REQUEST,
            )
        except subprocess.CalledProcessError as error:
            self._json_response(
                {"error": _database_error(error.stderr or error.stdout)},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _json_response(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _unauthorized_response(self):
        body = b'{"error":"API key required"}'
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("WWW-Authenticate", 'Bearer realm="gamedb"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _catalog_response(self, system_key=None, hide_rom_hacks=False):
        repository = self.server.repository
        revision = repository.catalog_revision()
        cache_key = f"system:{system_key}" if system_key else "manifest"
        if hide_rom_hacks:
            cache_key += ":without-rom-hacks"
        suffix = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:12]
        etag = f'"{revision}-{suffix}"'
        if system_key and repository.system_by_key(system_key, revision, hide_rom_hacks) is None:
            return self.send_error(HTTPStatus.NOT_FOUND)
        if self.headers.get("If-None-Match") == etag:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "private, no-cache")
            self.end_headers()
            return

        def load():
            if system_key:
                return repository.system_software(system_key, revision, hide_rom_hacks)
            return repository.catalog_manifest(revision, hide_rom_hacks)

        body = self.server.catalog_cache.get_bytes(
            etag, lambda: repository.load_at_revision(revision, load)
        )
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, no-cache")
        self.send_header("ETag", etag)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _asset_response(self, name, content_type, cache_control="no-store"):
        body = (ASSET_DIRECTORY / name).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(body)

    def _media_response(self, encoded_path, preview_size=None):
        try:
            decoded = unquote(encoded_path)
            if decoded.startswith("exo/"):
                source = re.fullmatch(r"exo/([0-9a-f]{64})/([0-9a-f]{64})",decoded)
                if not source:
                    return self.send_error(HTTPStatus.NOT_FOUND)
                return serve_related_media(self,source[2],revision=source[1],preview_size=preview_size)
            if decoded.startswith("launchbox/"):
                parts = decoded.split("/")
                if len(parts) != 3 or parts[1] not in {"boxart", "snap", "title", "logo"} or not valid_filename(parts[2]):
                    raise ValueError("Invalid LaunchBox media path")
                asset = self.server.repository.launchbox_image(decoded)
                if not asset:
                    return self.send_error(HTTPStatus.NOT_FOUND)
                try:
                    path = self.server.launchbox_cache.get(asset["fileName"], asset["crc32"])
                except (OSError, ValueError):
                    return self.send_error(HTTPStatus.BAD_GATEWAY, "LaunchBox image unavailable")
            else:
                path = _resolve_media_path(self.server.thumbnail_root, encoded_path)
            cache_control = "public, max-age=604800, immutable"
            etag = None
            if preview_size is not None:
                try:
                    path = self.server.preview_cache.get(path, preview_size)
                except (OSError, ValueError, SyntaxError):
                    if not path.is_file():
                        return self.send_error(HTTPStatus.NOT_FOUND)
                    self.send_response(HTTPStatus.TEMPORARY_REDIRECT)
                    self.send_header("Location", MEDIA_PREFIX + quote(decoded, safe="/"))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                etag = f'W/"{ArtworkPreviewCache.VERSION}-{path.stem}"'
                cache_control = "public, max-age=3600"
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(HTTPStatus.NOT_MODIFIED)
                    self.send_header("ETag", etag)
                    self.send_header("Cache-Control", cache_control)
                    self.end_headers()
                    return
            handle = path.open("rb")
        except (OSError, ValueError):
            return self.send_error(HTTPStatus.NOT_FOUND)
        with handle:
            content_type = "image/webp" if preview_size is not None else (
                mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(os.fstat(handle.fileno()).st_size))
            self.send_header("Cache-Control", cache_control)
            if etag:
                self.send_header("ETag", etag)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            while chunk := handle.read(1024 * 1024):
                self.wfile.write(chunk)

    def _load_install_manifest(self, release_signature):
        manifest = self.server.repository.install_manifest(release_signature)
        if not isinstance(manifest, dict):
            return None
        packages = manifest.get("packages")
        if not isinstance(packages, list) or not packages:
            return None
        enriched = []
        for item in packages:
            if not isinstance(item, dict):
                raise ValueError("Invalid package metadata")
            package = dict(item)
            path = _resolve_rom_path(self.server.rom_root, package.pop("resolvedPath", None))
            package["archiveSize"] = path.stat().st_size
            package["downloadUrl"] = (
                f"/api/v1/releases/{release_signature}/packages/"
                f"{package['packageSignature']}/download"
            )
            package["_path"] = path
            enriched.append(package)
        result = dict(manifest)
        result["packages"] = enriched
        return result

    def _install_manifest_response(self, release_signature):
        arcade = self.server.repository.arcade_install_manifest(release_signature)
        if arcade is not None:
            return self._json_response(public_manifest(prepare_manifest(arcade, self.server.rom_root)))
        manifest = self._load_install_manifest(release_signature)
        if manifest is None:
            return self.send_error(HTTPStatus.NOT_FOUND)
        public = dict(manifest)
        public["schemaVersion"] = 1
        public["packages"] = [
            {key: value for key, value in item.items() if key != "_path"}
            for item in manifest["packages"]
        ]
        return self._json_response(public)

    def _install_bundle_response(self, release_signature):
        source = self.server.repository.arcade_install_manifest(release_signature)
        if source is None:
            return self.send_error(HTTPStatus.NOT_FOUND)
        manifest = prepare_manifest(source, self.server.rom_root)
        if not manifest['complete']:
            return self._json_response(public_manifest(manifest), HTTPStatus.CONFLICT)
        # Generated bundles stream without a temporary multi-GB CHD copy.
        # Resumable downloads remain supported by the existing individual-package API.
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', 'application/zip')
        self.send_header('Content-Disposition', f"attachment; filename*=UTF-8''{quote(manifest['shortname'])}-arcade.zip")
        self.send_header('Cache-Control', 'private, no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        try:
            write_bundle(self.wfile, manifest)
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.log_message('arcade bundle interrupted release=%s', release_signature)

    def _package_response(self, release_signature, package_signature):
        manifest = self._load_install_manifest(release_signature)
        if manifest is None:
            return self.send_error(HTTPStatus.NOT_FOUND)
        package = next(
            (
                item for item in manifest["packages"]
                if item.get("packageSignature") == package_signature
            ),
            None,
        )
        if package is None:
            return self.send_error(HTTPStatus.NOT_FOUND)
        path = package["_path"]
        size = int(package["archiveSize"])
        try:
            requested = _byte_range(self.headers.get("Range"), size)
        except ValueError:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        start, end = requested or (0, size - 1)
        length = end - start + 1
        self.send_response(
            HTTPStatus.PARTIAL_CONTENT if requested else HTTPStatus.OK
        )
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", f'"{package_signature}"')
        self.send_header("Cache-Control", "private, max-age=31536000, immutable")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Disposition",
            f"attachment; filename*=UTF-8''{quote(str(package['archiveName']))}",
        )
        if requested:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        transferred = 0
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining:
                    chunk = handle.read(min(STREAM_CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
                    transferred += len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.log_message(
                "download release=%s package=%s status=%d bytes=%d range=%s",
                release_signature,
                package_signature,
                HTTPStatus.PARTIAL_CONTENT if requested else HTTPStatus.OK,
                transferred,
                self.headers.get("Range", "full"),
            )

    def log_message(self, format, *args):
        client = _request_client(
            self.headers.get("CF-Connecting-IP"), self.client_address[0]
        )
        print(f"{client} - {format % args}", flush=True)


class ExplorerServer(ThreadingHTTPServer):
    """Own the repository shared by explorer request handlers."""

    def __init__(self, address, handler, username):
        self.listing_engine = create_database_engine(pool_pre_ping=True)
        super().__init__(address, handler)
        self.repository = CatalogRepository(username, listing_engine=self.listing_engine)
        self.api_key = _api_key()
        self.rebuild_lock = threading.Lock()
        self.catalog_cache = JsonResponseCache(max_entries=128, max_bytes=128 * 1024 * 1024, ttl=None)
        self.corrections_enabled = _corrections_enabled()
        self.thumbnail_root = Path(os.environ.get(
            "GAMEDB_LIBRETRO_THUMBNAILS", "/data/libretro-thumbnails"
        ))
        self.launchbox_cache = LaunchBoxImageCache(os.environ.get(
            "GAMEDB_LAUNCHBOX_IMAGE_CACHE", "/data/media/launchbox"
        ))
        self.preview_cache = ArtworkPreviewCache(os.environ.get(
            "GAMEDB_PREVIEW_CACHE", PROJECT_ROOT / "data/media/previews"
        ))
        self.exo_root = Path(os.environ.get("GAMEDB_EXO_ROOT", "/mnt/exo"))
        vgm_root = os.environ.get("GAMEDB_VGM_ROOT")
        self.vgm_root = Path(vgm_root) if vgm_root else None
        self.rom_root = Path(os.environ.get("GAMEDB_ROM_ROOT", "/data/roms"))

    def server_close(self):
        super().server_close()
        self.listing_engine.dispose()

    def rebuild_software(self):
        self.repository.listing_cache.clear()
        try:
            subprocess.run(
                ["python", "-m", "gamedb.catalog", "rebuild", "--from-layer", "software"],
                check=True, capture_output=True, text=True,
            )
        finally:
            self.repository.listing_cache.clear()


def serve_explorer(host: str, port: int | None, username: str) -> int:
    ProjectEnvironment().load()
    port = _resolve_explorer_port(port)
    if not USERNAME.fullmatch(username):
        raise SystemExit("username must contain only letters, numbers, '.', '_' or '-'")
    if not 1 <= port <= 65535:
        raise SystemExit("port must be between 1 and 65535")

    server = ExplorerServer((host, port), ExplorerHandler, username)
    print(f"GameDB explorer for {username!r}: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
