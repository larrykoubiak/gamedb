"""Local HTTP transport and static assets for catalog exploration."""

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qs, urlparse

from gamedb.config import ProjectEnvironment
from gamedb.explorer.repository import CatalogRepository


ASSET_DIRECTORY = Path(__file__).with_name("assets")
PROJECT_ENV = Path(__file__).resolve().parent.parent / ".env"
USERNAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")
SYSTEM_TITLES = re.compile(r"/api/systems/([0-9]+)/titles")
TITLE_RELEASES = re.compile(r"/api/titles/([0-9]+)/releases")
PAGE_SIZE_MAXIMUM = 200
DEFAULT_PORT = 8000


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


def _database_error(stderr: str) -> str:
    if "connection to server" in stderr:
        return "Database connection failed. Check the project .env and that PostgreSQL is running."
    return stderr.strip().splitlines()[-1] if stderr else "Database query failed"


class ExplorerHandler(BaseHTTPRequestHandler):
    """Translate HTTP requests into read-only repository operations."""

    server_version = "GameDBExplorer/1"

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/systems":
                return self._json_response(self.server.repository.systems())

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

            match = TITLE_RELEASES.fullmatch(parsed.path)
            if match:
                return self._json_response(
                    self.server.repository.title_releases(int(match.group(1)))
                )

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
                {"error": _database_error(error.stderr)},
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
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}")


class ExplorerServer(ThreadingHTTPServer):
    """Own the repository shared by explorer request handlers."""

    def __init__(self, address, handler, username):
        super().__init__(address, handler)
        self.repository = CatalogRepository(username)


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
