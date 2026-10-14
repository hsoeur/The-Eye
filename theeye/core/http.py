"""Serveur HTTP : routeur à paramètres, réponses JSON, fichiers statiques sécurisés."""
import json
import logging
import mimetypes
import re
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

log = logging.getLogger("eye.http")
MAX_BODY = 1_000_000


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class Response:
    status: int = 200
    body: Any = None
    content_type: str = "application/json"
    headers: Dict[str, str] = field(default_factory=dict)


class Request:
    def __init__(self, method: str, path: str, query: Dict[str, str], headers, raw: bytes):
        self.method, self.path, self.query, self.headers = method, path, query, headers
        self.params: Dict[str, str] = {}
        self._raw = raw

    def json(self) -> Dict[str, Any]:
        if not self._raw:
            return {}
        try:
            data = json.loads(self._raw)
        except ValueError:
            raise HttpError(400, "JSON invalide")
        if not isinstance(data, dict):
            raise HttpError(400, "objet JSON attendu")
        return data


Handler = Callable[[Request], Any]


class Router:
    def __init__(self, prefix: str = "", parent: Optional["Router"] = None):
        self._prefix = prefix
        self._routes: List[Tuple[str, "re.Pattern", str, Handler]] = parent._routes if parent else []

    def scoped(self, prefix: str) -> "Router":
        return Router(self._prefix + prefix, self)

    def add(self, method: str, pattern: str, handler: Handler) -> None:
        full = self._prefix + pattern
        rx = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", full) + "$")
        if any(m == method and r.pattern == rx.pattern for m, r, _, _ in self._routes):
            raise ValueError(f"route déjà déclarée : {method} {full}")
        self._routes.append((method, rx, full, handler))

    def get(self, pattern, handler): self.add("GET", pattern, handler)
    def post(self, pattern, handler): self.add("POST", pattern, handler)
    def delete(self, pattern, handler): self.add("DELETE", pattern, handler)

    def resolve(self, method: str, path: str) -> Tuple[Handler, Dict[str, str]]:
        allowed = False
        for m, rx, _, handler in self._routes:
            match = rx.match(path)
            if match:
                if m == method:
                    return handler, {k: unquote(v) for k, v in match.groupdict().items()}
                allowed = True
        raise HttpError(405 if allowed else 404, "méthode non autorisée" if allowed else "introuvable")

    def paths(self) -> List[str]:
        return [f"{m} {p}" for m, _, p, _ in self._routes]


class StaticFiles:
    """Associe des préfixes d'URL à des dossiers ; refuse toute sortie du dossier."""

    def __init__(self):
        self._mounts: List[Tuple[str, Path]] = []

    def mount(self, prefix: str, directory: Path) -> None:
        self._mounts.append((prefix, Path(directory).resolve()))
        self._mounts.sort(key=lambda m: -len(m[0]))

    def find(self, url_path: str) -> Optional[Path]:
        if url_path == "/":
            url_path = "/index.html"
        for prefix, root in self._mounts:
            if url_path.startswith(prefix):
                f = (root / unquote(url_path[len(prefix):]).lstrip("/\\")).resolve()
                if root in f.parents and f.is_file():
                    return f
        return None


class Server:
    def __init__(self, host: str, port: int, router: Router, static: StaticFiles):
        server = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _serve(self, method: str):
                parts = urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    if length > MAX_BODY:
                        raise HttpError(413, "requête trop volumineuse")
                    raw = self.rfile.read(length) if length else b""
                    resp = server._dispatch(method, parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()},
                                            self.headers, raw)
                except HttpError as e:
                    resp = Response(e.status, {"error": e.message})
                except Exception:
                    log.exception("erreur non gérée sur %s %s", method, parts.path)
                    resp = Response(500, {"error": "erreur interne"})
                body = resp.body if isinstance(resp.body, bytes) else json.dumps(resp.body).encode()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                for k, v in resp.headers.items():
                    self.send_header(k, v)
                self.end_headers()
                if method != "HEAD":
                    self.wfile.write(body)

            def do_GET(self): self._serve("GET")
            def do_POST(self): self._serve("POST")
            def do_DELETE(self): self._serve("DELETE")

        self.router, self.static = router, static
        self.httpd = ThreadingHTTPServer((host, port), _Handler)
        self.httpd.daemon_threads = True

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def _dispatch(self, method, path, query, headers, raw) -> Response:
        if path.startswith("/api/"):
            handler, params = self.router.resolve(method, path)
            req = Request(method, path, query, headers, raw)
            req.params = params
            result = handler(req)
            if isinstance(result, Response):
                return result
            if isinstance(result, tuple):
                return Response(result[0], result[1])
            return Response(200, result if result is not None else {"ok": True})
        if method != "GET":
            raise HttpError(405, "méthode non autorisée")
        f = self.static.find(path)
        if not f and "." not in path.rsplit("/", 1)[-1]:
            f = self.static.find("/")  # repli SPA : le routeur côté client gère l'URL
        if not f:
            raise HttpError(404, "introuvable")
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        cache = "public, max-age=31536000, immutable" if path.startswith("/assets/") else "no-cache"
        return Response(200, f.read_bytes(), ctype, {"Cache-Control": cache})

    def serve_forever(self) -> None:
        self.httpd.serve_forever(poll_interval=0.5)

    def start_background(self) -> threading.Thread:
        t = threading.Thread(target=self.serve_forever, daemon=True, name="eye-http")
        t.start()
        return t

    def shutdown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
