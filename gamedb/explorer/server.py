"""Local HTTP transport and static assets for catalog exploration."""

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import threading
from urllib.parse import parse_qs, unquote, urlparse

from gamedb.config import ProjectEnvironment
from gamedb.explorer.repository import CatalogRepository


ASSET_DIRECTORY = Path(__file__).with_name("assets")
PROJECT_ENV = Path(__file__).resolve().parent.parent / ".env"
USERNAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")
SYSTEM_TITLES = re.compile(r"/api/systems/([0-9]+)/titles")
SOFTWARE_RELEASES = re.compile(r"/api/software/([0-9]+)/releases")
CORRECTION_TARGETS = re.compile(r"/api/systems/([0-9]+)/correction-targets")
PAGE_SIZE_MAXIMUM = 200
DEFAULT_PORT = 8000
MEDIA_PREFIX = "/media/"
MEDIA_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})


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


def _database_error(stderr: str) -> str:
    if "connection to server" in stderr:
        return "Database connection failed. Check the project .env and that PostgreSQL is running."
    return stderr.strip().splitlines()[-1] if stderr else "Database query failed"


class ExplorerHandler(BaseHTTPRequestHandler):
    """Translate HTTP requests into catalog and correction operations."""

    server_version = "GameDBExplorer/1"

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/systems":
                return self._json_response(self.server.repository.systems())
            if parsed.path == "/api/capabilities":
                return self._json_response({
                    "softwareCorrections": self.server.corrections_enabled,
                })
            if parsed.path.startswith(MEDIA_PREFIX):
                return self._media_response(parsed.path[len(MEDIA_PREFIX):])

            match = SYSTEM_TITLES.fullmatch(parsed.path)
            if match:
                query = parse_qs(parsed.query)
                page = max(1, int(query.get("page", ["1"])[0]))
                page_size = min(
                    PAGE_SIZE_MAXIMUM,
                    max(1, int(query.get("page_size", ["100"])[0])),
                )
                title_filter = query.get("q", [""])[0].strip()[:100]
                payload = self.server.repository.titles(
                    int(match.group(1)),
                    page_size,
                    (page - 1) * page_size,
                    title_filter,
                )
                payload["page"] = page
                payload["pageSize"] = page_size
                return self._json_response(payload)

            match = SOFTWARE_RELEASES.fullmatch(parsed.path)
            if match:
                return self._json_response(
                    self.server.repository.software_releases(int(match.group(1)))
                )

            match = CORRECTION_TARGETS.fullmatch(parsed.path)
            if match:
                if not self.server.corrections_enabled:
                    return self._json_response(
                        {"error": "Software corrections are disabled"},
                        HTTPStatus.FORBIDDEN,
                    )
                query = parse_qs(parsed.query)
                software_id = int(query.get("exclude_software_id", ["0"])[0])
                title_filter = query.get("q", [""])[0].strip()[:100]
                return self._json_response(self.server.repository.correction_targets(
                    int(match.group(1)), software_id, title_filter
                ))

            if parsed.path in ("/", "/index.html"):
                return self._asset_response("index.html", "text/html; charset=utf-8")
            if parsed.path == "/app.js":
                return self._asset_response("app.js", "text/javascript; charset=utf-8")
            if parsed.path == "/styles.css":
                return self._asset_response("styles.css", "text/css; charset=utf-8")
            self.send_error(HTTPStatus.NOT_FOUND)
        except (ValueError, TypeError):
            self._json_response(
                {"error": "Invalid request parameters"}, HTTPStatus.BAD_REQUEST
            )
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

    def _asset_response(self, name, content_type):
        body = (ASSET_DIRECTORY / name).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _media_response(self, encoded_path):
        try:
            path = _resolve_media_path(self.server.thumbnail_root, encoded_path)
            handle = path.open("rb")
        except (OSError, ValueError):
            return self.send_error(HTTPStatus.NOT_FOUND)
        with handle:
            content_type = (
                mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(os.fstat(handle.fileno()).st_size))
            self.send_header("Cache-Control", "public, max-age=604800, immutable")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            while chunk := handle.read(1024 * 1024):
                self.wfile.write(chunk)

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}")


class ExplorerServer(ThreadingHTTPServer):
    """Own the repository shared by explorer request handlers."""

    def __init__(self, address, handler, username):
        super().__init__(address, handler)
        self.repository = CatalogRepository(username)
        self.rebuild_lock = threading.Lock()
        self.corrections_enabled = _corrections_enabled()
        self.thumbnail_root = Path(os.environ.get(
            "GAMEDB_LIBRETRO_THUMBNAILS", "/data/libretro-thumbnails"
        ))

    @staticmethod
    def rebuild_software():
        subprocess.run(
            ["python", "-m", "gamedb.catalog", "rebuild", "--from-layer", "software"],
            check=True, capture_output=True, text=True,
        )


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
