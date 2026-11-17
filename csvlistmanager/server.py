"""Localhost-only standard-library HTTP JSON service."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .app import Application
from .errors import CSVListManagerError, NotFoundError, ValidationError


MAX_BODY = 2 * 1024 * 1024
STATIC_ROOT = Path(__file__).with_name("static")
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/model.js": ("model.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}
CONTENT_SECURITY_POLICY = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"


class CSVListManagerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], application: Application):
        self.application = application
        super().__init__(address, RequestHandler)


class RequestHandler(BaseHTTPRequestHandler):
    server: CSVListManagerHTTPServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        self._handle("POST")

    def _handle(self, method: str) -> None:
        try:
            self._dispatch(method)
        except CSVListManagerError as error:
            self._json(error.status, {"error": {"code": error.code, "message": error.message}})
        except Exception:
            self._json(500, {"error": {"code": "internal_error", "message": "Unexpected service error"}})

    def _dispatch(self, method: str) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        app = self.server.application
        if method == "GET":
            if path in STATIC_FILES:
                self._static(path)
                return
            if path == "/api/health":
                self._json(200, {"status": "ok"})
                return
            if path == "/api/repositories":
                self._json(200, app.list_repositories())
                return
            if path == "/api/repository":
                self._json(200, app.load_repository(self._query(query, "repository")))
                return
            if path == "/api/log":
                self._json(200, app.read_log(self._query(query, "repository"), self._query(query, "limit") or 500))
                return
        else:
            payload = self._payload()
            if path == "/api/repositories/select":
                self._json(200, app.select_repository(payload.get("repository")))
                return
            if path == "/api/preferences/mode":
                self._json(200, app.set_mode(payload.get("repository"), payload.get("mode")))
                return
            if path == "/api/preferences/view":
                self._json(200, app.set_view_preferences(payload))
                return
            if path == "/api/save":
                self._json(200, app.save(payload))
                return
            if path == "/api/scripts/run":
                self._json(200, app.run_script(payload.get("repository"), payload.get("script")))
                return
        raise NotFoundError(f"No endpoint for {method} {path}")

    @staticmethod
    def _query(query: dict[str, list[str]], name: str) -> str | None:
        values = query.get(name)
        return values[-1] if values else None

    def _payload(self) -> dict[str, Any]:
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            raise ValidationError("Content-Length is required")
        try:
            length = int(length_header)
        except ValueError as error:
            raise ValidationError("Invalid Content-Length") from error
        if length < 0 or length > MAX_BODY:
            raise ValidationError(f"JSON body must not exceed {MAX_BODY} bytes")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValidationError(f"Invalid JSON body: {error}") from error
        if not isinstance(value, dict):
            raise ValidationError("JSON body must be an object")
        return value

    def _json(self, status: int, value: dict[str, Any]) -> None:
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _static(self, request_path: str) -> None:
        filename, content_type = STATIC_FILES[request_path]
        try:
            data = (STATIC_ROOT / filename).read_bytes()
        except OSError:
            raise NotFoundError(f"Interface asset {filename} is unavailable")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)


def make_server(application: Application, host: str = "127.0.0.1", port: int = 8765) -> CSVListManagerHTTPServer:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise ValidationError("Host must be a numeric loopback address, such as 127.0.0.1") from error
    if not address.is_loopback or address.version != 4:
        raise ValidationError("The service may bind only to an IPv4 loopback address")
    if not 0 <= port <= 65535:
        raise ValidationError("Port must be between 0 and 65535")
    return CSVListManagerHTTPServer((host, port), application)
