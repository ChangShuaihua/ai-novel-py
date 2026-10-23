"""本机写作控制室。只把宿主快照和意图送进浏览器。"""

import json
import logging
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from ainovel.entry.desk import Desk, DeskError

logger = logging.getLogger(__name__)
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")

_MAX_BODY = 1_000_000


def serve(host: str = "127.0.0.1", port: int = 8765, desk: Desk | None = None, static_dir: Path | None = None) -> None:
    studio = desk or Desk()
    root = Path(static_dir) if static_dir is not None else _dist_dir()
    server = ThreadingHTTPServer((host, port), _handler(studio, root))
    print(f"写作控制室 http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        studio.shutdown()
        server.server_close()


def _dist_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "web" / "dist"


def _handler(desk: Desk, static_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_OPTIONS(self) -> None:
            self._bytes(204, "text/plain; charset=utf-8", b"", cache=False)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/library":
                self._send(200, desk.library())
                return
            if parsed.path == "/api/model":
                self._send(200, desk.model_settings())
                return
            if parsed.path == "/api/snapshot":
                query = parse_qs(parsed.query)
                directory = (query.get("directory") or [""])[0]
                try:
                    self._send(200, desk.snapshot(directory))
                except DeskError as exc:
                    self._send(404, {"error": str(exc)})
                return
            self._file(parsed.path)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            try:
                payload = self._body()
            except DeskError as exc:
                self._send(400, {"error": str(exc)})
                return
            try:
                if parsed.path == "/api/library":
                    action = str(payload.get("action") or "attach")
                    directory = str(payload.get("directory") or "")
                    if action == "discard":
                        self._send(200, desk.discard(directory))
                    elif action == "restore":
                        self._send(200, desk.restore(directory))
                    elif action == "empty":
                        self._send(200, desk.empty_trash())
                    elif action == "attach":
                        self._send(200, desk.attach(directory))
                    else:
                        raise DeskError(f"未知书架动作 {action}")
                    return
                if parsed.path == "/api/directory":
                    self._send(200, desk.pick_directory())
                    return
                if parsed.path == "/api/save-file":
                    self._send(200, desk.pick_save_file(str(payload.get("name") or "")))
                    return
                if parsed.path == "/api/model":
                    self._send(200, desk.save_model(payload))
                    return
                if parsed.path == "/api/intent":
                    self._send(200, desk.intent(payload))
                    return
            except DeskError as exc:
                self._send(400, {"error": str(exc)})
                return
            except Exception as exc:
                logger.exception("入口失败")
                self._send(500, {"error": _short(exc)})
                return
            self._send(404, {"error": "没有这个接口"})

        def log_message(self, fmt: str, *args) -> None:
            if self.path.startswith("/api/snapshot"):
                return
            super().log_message(fmt, *args)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > _MAX_BODY:
                raise DeskError("请求过大")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DeskError("请求不是 JSON") from exc
            if not isinstance(payload, dict):
                raise DeskError("请求必须是对象")
            return payload

        def _file(self, path: str) -> None:
            if path.startswith("/api/"):
                self._send(404, {"error": "没有这个接口"})
                return
            target = _safe_file(static_dir, path)
            if target is None or not target.is_file():
                target = static_dir / "index.html"
            if not target.is_file():
                body = _missing_page().encode("utf-8")
                self._bytes(200, "text/html; charset=utf-8", body)
                return
            mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if mime.startswith("text/") or mime in {"application/javascript", "application/json"}:
                mime += "; charset=utf-8"
            self._bytes(200, mime, target.read_bytes(), cache=target.suffix != ".html")

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._bytes(status, "application/json; charset=utf-8", body, cache=False)

        def _bytes(self, status: int, content_type: str, body: bytes, *, cache: bool = True) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store" if not cache else "public, max-age=3600")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

    return Handler


def _safe_file(root: Path, path: str) -> Path | None:
    if not root.is_dir():
        return None
    relative = unquote(path).lstrip("/")
    if not relative:
        return root / "index.html"
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _missing_page() -> str:
    return """<!DOCTYPE html>
<meta charset="utf-8">
<title>ainovel</title>
<p>界面还没有构建。在 web 目录执行 npm install，然后 npm run build。</p>
"""


def _short(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    if len(text) > 160:
        return text[:160] + "…"
    return text
