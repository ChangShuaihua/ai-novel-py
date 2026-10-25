"""写作控制室的登记和登录。浏览器使用一对 JWT，命令行不经过这里。"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ainovel.host.config import config_dir

REFRESH_COOKIE = "ainovel_refresh"
ACCESS_TTL = 15 * 60
REFRESH_TTL = 7 * 24 * 60 * 60
_DEFAULT_N = 2**14
_DUMMY_SALT = b"ainovel-missing-user"


class AuthError(RuntimeError):
    def __init__(self, message: str, status: int = 401) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str
    expires_in: int
    username: str
    user_id: str


class AuthStore:
    """账号写在用户目录。访问令牌短，刷新令牌长，刷新时旧的立即作废。"""

    def __init__(
        self,
        root: Path | None = None,
        *,
        clock=None,
        attempts: int = 8,
        window: float = 600,
        access_ttl: float = ACCESS_TTL,
        refresh_ttl: float = REFRESH_TTL,
        n: int = _DEFAULT_N,
    ) -> None:
        self.root = root or config_dir()
        self._clock = clock or time.time
        self.attempts = attempts
        self.window = window
        self.access_ttl = access_ttl
        self.refresh_ttl = refresh_ttl
        self.n = n
        self._lock = threading.RLock()
        self._failures: dict[str, list[float]] = {}

    def register(self, username: str, password: str, client: str) -> Tokens:
        name = clean_username(username)
        secret = clean_password(password)
        with self._lock:
            if self._blocked(client):
                raise AuthError("试得太勤，过一会儿再来。", 429)
            users = self._load()
            if _find_name(users, name) is not None:
                raise AuthError("这个名字已经有人用了。", 409)
            salt = secrets.token_bytes(16)
            user = {
                "id": secrets.token_hex(8),
                "username": name,
                "salt": base64.b64encode(salt).decode("ascii"),
                "hash": base64.b64encode(_scrypt(secret, salt, self.n)).decode("ascii"),
                "n": self.n,
                "generation": 1,
                "refresh_jti": "",
            }
            users.append(user)
            return self._issue(users, user)

    def login(self, username: str, password: str, client: str) -> Tokens:
        with self._lock:
            if self._blocked(client):
                raise AuthError("试得太勤，过一会儿再来。", 429)
            users = self._load()
            user = _find_name(users, username.strip())
            if user is None or not _password_matches(password, user):
                if user is None and len(password) <= 200:
                    _scrypt(password, _DUMMY_SALT, self.n)
                self._note_failure(client)
                raise AuthError("账号或密码不对。", 401)
            self._failures.pop(client, None)
            return self._issue(users, user)

    def refresh(self, refresh_token: str) -> Tokens:
        payload = _read_jwt(refresh_token, self._secret(), "refresh", int(self._clock()), "登录已失效。")
        with self._lock:
            users = self._load()
            user = _find_id(users, str(payload.get("sub") or ""))
            if user is None or int(payload.get("ver") or 0) != int(user["generation"]):
                raise AuthError("登录已失效。", 401)
            presented = str(payload.get("jti") or "")
            current = str(user.get("refresh_jti") or "")
            if not current or not _same_text(presented, current):
                user["refresh_jti"] = ""
                self._save(users)
                raise AuthError("登录已失效。", 401)
            return self._issue(users, user)

    def logout(self, access_token: str, refresh_token: str) -> None:
        with self._lock:
            users = self._load()
            user = self._user_for_logout(users, access_token, "access")
            if user is None:
                user = self._user_for_logout(users, refresh_token, "refresh")
            if user is None:
                return
            user["generation"] = int(user["generation"]) + 1
            user["refresh_jti"] = ""
            self._save(users)

    def authenticate(self, access_token: str) -> dict:
        if not access_token:
            raise AuthError("先登录。", 401)
        payload = _read_jwt(access_token, self._secret(), "access", int(self._clock()), "登录已过期。")
        with self._lock:
            user = _find_id(self._load(), str(payload.get("sub") or ""))
            if user is None or int(payload.get("ver") or 0) != int(user["generation"]):
                raise AuthError("先登录。", 401)
            return {"id": user["id"], "username": user["username"]}

    def change_password(self, access_token: str, current: str, username: str, password: str) -> Tokens:
        secret = clean_password(password)
        renamed = clean_username(username) if username.strip() else ""
        identity = self.authenticate(access_token)
        with self._lock:
            users = self._load()
            user = _find_id(users, identity["id"])
            if user is None:
                raise AuthError("先登录。", 401)
            if not _password_matches(current, user):
                raise AuthError("现在的密码不对。", 400)
            if renamed and renamed != user["username"] and _find_name(users, renamed) is not None:
                raise AuthError("这个名字已经有人用了。", 409)
            if renamed:
                user["username"] = renamed
            salt = secrets.token_bytes(16)
            user["salt"] = base64.b64encode(salt).decode("ascii")
            user["hash"] = base64.b64encode(_scrypt(secret, salt, int(user["n"]))).decode("ascii")
            user["generation"] = int(user["generation"]) + 1
            user["refresh_jti"] = ""
            return self._issue(users, user)

    def refresh_cookie(self, refresh_token: str) -> str:
        return (
            f"{REFRESH_COOKIE}={refresh_token}; HttpOnly; SameSite=Lax; Path=/api; "
            f"Max-Age={max(0, int(self.refresh_ttl))}"
        )

    def clear_cookie(self) -> str:
        return f"{REFRESH_COOKIE}=; HttpOnly; SameSite=Lax; Path=/api; Max-Age=0"

    def _issue(self, users: list[dict], user: dict) -> Tokens:
        now = int(self._clock())
        jti = secrets.token_hex(16)
        user["refresh_jti"] = jti
        self._save(users)
        access = _jwt(
            {
                "sub": user["id"],
                "name": user["username"],
                "typ": "access",
                "ver": int(user["generation"]),
                "jti": secrets.token_hex(8),
                "iat": now,
                "exp": now + int(self.access_ttl),
            },
            self._secret(),
        )
        refresh = _jwt(
            {
                "sub": user["id"],
                "typ": "refresh",
                "ver": int(user["generation"]),
                "jti": jti,
                "iat": now,
                "exp": now + int(self.refresh_ttl),
            },
            self._secret(),
        )
        return Tokens(access, refresh, int(self.access_ttl), user["username"], user["id"])

    def _user_for_logout(self, users: list[dict], token: str, typ: str) -> dict | None:
        if not token:
            return None
        try:
            payload = _read_jwt(token, self._secret(), typ, int(self._clock()), "登录已失效。")
        except AuthError:
            return None
        user = _find_id(users, str(payload.get("sub") or ""))
        if user is None or int(payload.get("ver") or 0) != int(user["generation"]):
            return None
        return user

    def _blocked(self, client: str) -> bool:
        now = self._clock()
        recent = [item for item in self._failures.get(client, []) if now - item < self.window]
        self._failures[client] = recent
        return len(recent) >= self.attempts

    def _note_failure(self, client: str) -> None:
        now = self._clock()
        recent = [item for item in self._failures.get(client, []) if now - item < self.window]
        recent.append(now)
        self._failures[client] = recent

    def _secret(self) -> bytes:
        with self._lock:
            path = self.root / "jwt.secret"
            if path.is_file():
                data = path.read_bytes()
                if len(data) < 32:
                    raise AuthError(f"无法读取密钥 {path}。", 500)
                return data
            data = secrets.token_bytes(32)
            _write_secret_bytes(path, data)
            return data

    def _load(self) -> list[dict]:
        path = self.root / "users.json"
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AuthError(f"无法读取账号文件 {path}。", 500) from exc
        users = raw.get("users") if isinstance(raw, dict) else None
        if not isinstance(users, list):
            raise AuthError(f"无法读取账号文件 {path}。", 500)
        for item in users:
            if not isinstance(item, dict) or not _stored_user(item):
                raise AuthError(f"无法读取账号文件 {path}。", 500)
        return users

    def _save(self, users: list[dict]) -> None:
        _write_secret(self.root / "users.json", json.dumps({"users": users}, ensure_ascii=False, indent=2) + "\n")


def clean_username(name: str) -> str:
    text = name.strip()
    if not text or len(text) > 40 or any(ord(ch) < 32 for ch in text):
        raise AuthError("名字要在 1 到 40 个字之间。", 400)
    return text


def clean_password(password: str) -> str:
    if len(password) < 8 or len(password) > 200:
        raise AuthError("密码至少 8 位，最长 200 位。", 400)
    return password


def read_cookie(header: str | None, name: str = REFRESH_COOKIE) -> str:
    if not header:
        return ""
    for part in header.split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key == name:
            return value.strip()
    return ""


def _password_matches(password: str, user: dict) -> bool:
    if len(password) > 200:
        return False
    try:
        salt = base64.b64decode(str(user.get("salt") or ""), validate=True)
        expected = base64.b64decode(str(user.get("hash") or ""), validate=True)
        n = int(user.get("n"))
    except (ValueError, TypeError):
        return False
    if not _scrypt_n(n) or len(expected) != 32:
        return False
    try:
        digest = _scrypt(password, salt, n)
    except ValueError:
        return False
    return hmac.compare_digest(digest, expected)


def _find_name(users: list[dict], username: str) -> dict | None:
    for user in users:
        if user["username"] == username:
            return user
    return None


def _find_id(users: list[dict], user_id: str) -> dict | None:
    for user in users:
        if user["id"] == user_id:
            return user
    return None


def _stored_user(item: dict) -> bool:
    try:
        clean_username(str(item.get("username") or ""))
        generation = int(item.get("generation"))
        n = int(item.get("n"))
    except (AuthError, TypeError, ValueError):
        return False
    user_id = str(item.get("id") or "")
    return bool(user_id.isalnum() and generation >= 1 and _scrypt_n(n) and item.get("salt") and item.get("hash"))


def _jwt(payload: dict, secret: bytes) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    body = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signature = _b64(hmac.new(secret, f"{header}.{body}".encode("ascii"), hashlib.sha256).digest())
    return f"{header}.{body}.{signature}"


def _read_jwt(token: str, secret: bytes, typ: str, now: int, expired_message: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise AuthError("先登录。", 401)
    try:
        header = json.loads(_unb64(parts[0]))
        payload = json.loads(_unb64(parts[1]))
        actual = _unb64(parts[2])
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthError("先登录。", 401) from exc
    if not isinstance(header, dict) or header.get("alg") != "HS256" or not isinstance(payload, dict):
        raise AuthError("先登录。", 401)
    expected = hmac.new(secret, f"{parts[0]}.{parts[1]}".encode("ascii"), hashlib.sha256).digest()
    if len(actual) != len(expected) or not hmac.compare_digest(actual, expected):
        raise AuthError("先登录。", 401)
    if payload.get("typ") != typ:
        raise AuthError("先登录。", 401)
    try:
        expires = int(payload.get("exp"))
    except (TypeError, ValueError) as exc:
        raise AuthError("先登录。", 401) from exc
    if expires <= now:
        raise AuthError(expired_message, 401)
    return payload


def _scrypt(password: str, salt: bytes, n: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)


def _scrypt_n(n: int) -> bool:
    return isinstance(n, int) and not isinstance(n, bool) and 2**10 <= n <= 2**15 and n & (n - 1) == 0


def _same_text(left: str, right: str) -> bool:
    a = left.encode("utf-8")
    b = right.encode("utf-8")
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    if not text or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in text):
        raise ValueError
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _write_secret(path: Path, text: str) -> None:
    _write_secret_bytes(path, text.encode("utf-8"))


def _write_secret_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    temporary.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
