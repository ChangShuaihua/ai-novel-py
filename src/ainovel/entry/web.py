"""写作接口。页面由单独的前端提供，这里只回答 /api。"""

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ainovel.entry.auth import AuthError, AuthStore, Tokens, read_cookie
from ainovel.entry.desk import Desk, DeskError

logger = logging.getLogger(__name__)

_MAX_BODY = 1_000_000


class Accounts:
    """每个名字一份书架、模型配置和书目录。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()
        self._desks: dict[str, Desk] = {}

    def desk_for(self, user_id: str) -> Desk:
        if not user_id.isalnum():
            raise DeskError("先登录。")
        with self._lock:
            desk = self._desks.get(user_id)
            if desk is None:
                home = self.root / "accounts" / user_id
                desk = Desk(
                    library_path=home / "library.json",
                    config_path=home / "config.json",
                    books_root=home / "books",
                )
                self._desks[user_id] = desk
            return desk

    def shutdown(self) -> None:
        with self._lock:
            desks = list(self._desks.values())
        for desk in desks:
            desk.shutdown()


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    auth: AuthStore | None = None,
    accounts: Accounts | None = None,
    origins: frozenset[str] | None = None,
) -> None:
    door = auth or AuthStore()
    shelf = accounts or Accounts(door.root)
    allowed = origins if origins is not None else cors_origins()
    server = ThreadingHTTPServer((host, port), _handler(shelf, door, allowed))
    print(f"写作接口 http://{host}:{port}", flush=True)
    if allowed:
        print("允许的页面来源 " + ", ".join(sorted(allowed)), flush=True)
    try:
        server.serve_forever()
    finally:
        shelf.shutdown()
        server.server_close()


def cors_origins() -> frozenset[str]:
    raw = os.environ.get("AINOVEL_CORS_ORIGINS", "http://127.0.0.1:5173")
    return frozenset(item.strip().rstrip("/") for item in raw.split(",") if item.strip())


def _handler(accounts: Accounts, auth: AuthStore, origins: frozenset[str] | None = None):
    allowed = origins or frozenset()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_OPTIONS(self) -> None:
            if not self._guard():
                self._send(403, {"error": "拒绝跨站请求。"})
                return
            self._bytes(204, "text/plain; charset=utf-8", b"", cache=False, preflight=True)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                if not self._guard():
                    self._send(403, {"error": "拒绝跨站请求。"})
                    return
                if parsed.path == "/api/session":
                    self._session()
                    return
                desk = self._desk()
                if desk is None:
                    return
                if parsed.path == "/api/library":
                    self._send(200, desk.library())
                    return
                if parsed.path == "/api/model":
                    self._send(200, self._owned(desk.model_settings()))
                    return
                if parsed.path == "/api/snapshot":
                    query = parse_qs(parsed.query)
                    directory = (query.get("directory") or [""])[0]
                    try:
                        self._send(200, desk.snapshot(directory))
                    except DeskError as exc:
                        self._send(404, {"error": str(exc)})
                    return
                self._send(404, {"error": "没有这个接口"})
                return
            self._send(404, {"error": "没有这个接口"})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if not self._guard():
                self._drain()
                self._send(403, {"error": "拒绝跨站请求。"})
                return
            if parsed.path == "/api/register":
                self._register()
                return
            if parsed.path == "/api/login":
                self._login()
                return
            if parsed.path == "/api/refresh":
                self._refresh()
                return
            if parsed.path == "/api/logout":
                self._logout()
                return
            desk = self._desk()
            if desk is None:
                self._drain()
                return
            if parsed.path == "/api/password":
                self._password()
                return
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
                if parsed.path == "/api/model/check":
                    self._send(200, self._owned(desk.probe_model(payload)))
                    return
                if parsed.path == "/api/model":
                    self._send(200, self._owned(desk.save_model(payload)))
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

        def _session(self) -> None:
            try:
                user = auth.authenticate(self._bearer())
            except AuthError:
                self._send(200, {"authenticated": False, "username": ""})
                return
            self._send(200, {"authenticated": True, "username": user["username"]})

        def _register(self) -> None:
            try:
                payload = self._body()
            except DeskError as exc:
                self._send(400, {"error": str(exc)})
                return
            try:
                tokens = auth.register(
                    str(payload.get("username") or ""),
                    str(payload.get("password") or ""),
                    str(self.client_address[0]),
                )
            except AuthError as exc:
                self._send(exc.status, {"error": str(exc)})
                return
            self._credential(tokens)

        def _login(self) -> None:
            try:
                payload = self._body()
            except DeskError as exc:
                self._send(400, {"error": str(exc)})
                return
            try:
                tokens = auth.login(
                    str(payload.get("username") or ""),
                    str(payload.get("password") or ""),
                    str(self.client_address[0]),
                )
            except AuthError as exc:
                self._send(exc.status, {"error": str(exc)})
                return
            self._credential(tokens)

        def _refresh(self) -> None:
            try:
                payload = self._body()
            except DeskError as exc:
                self._send(400, {"error": str(exc)})
                return
            token = str(payload.get("refresh_token") or "") or read_cookie(self.headers.get("Cookie"))
            try:
                tokens = auth.refresh(token)
            except AuthError as exc:
                cookies = (auth.clear_cookie(),) if exc.status == 401 else ()
                self._send(exc.status, {"error": str(exc)}, cookies=cookies)
                return
            self._credential(tokens)

        def _logout(self) -> None:
            self._drain()
            auth.logout(self._bearer(), read_cookie(self.headers.get("Cookie")))
            self._send(200, {"authenticated": False, "username": ""}, cookies=(auth.clear_cookie(),))

        def _password(self) -> None:
            try:
                payload = self._body()
            except DeskError as exc:
                self._send(400, {"error": str(exc)})
                return
            try:
                tokens = auth.change_password(
                    self._bearer(),
                    str(payload.get("current") or ""),
                    str(payload.get("username") or ""),
                    str(payload.get("password") or ""),
                )
            except AuthError as exc:
                self._send(exc.status, {"error": str(exc)})
                return
            self._credential(tokens)

        def _credential(self, tokens: Tokens) -> None:
            self._send(
                200,
                {
                    "authenticated": True,
                    "username": tokens.username,
                    "access_token": tokens.access_token,
                    "refresh_token": tokens.refresh_token,
                    "token_type": "bearer",
                    "expires_in": tokens.expires_in,
                },
                cookies=(auth.refresh_cookie(tokens.refresh_token),),
            )

        def _desk(self) -> Desk | None:
            try:
                user = auth.authenticate(self._bearer())
            except AuthError as exc:
                self._send(exc.status, {"error": str(exc)})
                return None
            self._account = user
            try:
                return accounts.desk_for(user["id"])
            except DeskError as exc:
                self._send(401, {"error": str(exc)})
                return None

        def _owned(self, view: dict) -> dict:
            user = getattr(self, "_account", None) or {}
            view["username"] = str(user.get("username") or "")
            return view

        def _bearer(self) -> str:
            scheme, _, token = (self.headers.get("Authorization") or "").partition(" ")
            if scheme.lower() != "bearer":
                return ""
            return token.strip()

        def _guard(self) -> bool:
            self._cors_origin = ""
            origin = self.headers.get("Origin")
            if origin:
                cleaned = origin.strip().rstrip("/")
                parsed = urlparse(cleaned)
                same_host = parsed.netloc == (self.headers.get("Host") or "")
                if parsed.scheme in {"http", "https"} and (cleaned in allowed or same_host):
                    self._cors_origin = cleaned
                    return True
                return False
            return self.headers.get("Sec-Fetch-Site") != "cross-site"

        def _drain(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0 or length > _MAX_BODY:
                self.close_connection = True
                return
            if length:
                self.rfile.read(length)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > _MAX_BODY:
                self.close_connection = True
                raise DeskError("请求过大")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DeskError("请求不是 JSON") from exc
            if not isinstance(payload, dict):
                raise DeskError("请求必须是对象")
            return payload

        def _send(self, status: int, payload: dict, cookies: tuple[str, ...] = ()) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._bytes(status, "application/json; charset=utf-8", body, cache=False, cookies=cookies)

        def _bytes(
            self,
            status: int,
            content_type: str,
            body: bytes,
            *,
            cache: bool = True,
            cookies: tuple[str, ...] = (),
            preflight: bool = False,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store" if not cache else "public, max-age=3600")
            origin = getattr(self, "_cors_origin", "")
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.send_header("Vary", "Origin")
            if preflight:
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Max-Age", "600")
            for cookie in cookies:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

    return Handler


def _short(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    if len(text) > 160:
        return text[:160] + "…"
    return text
