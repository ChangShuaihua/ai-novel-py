"""登记和登录使用一对 JWT。访问令牌短，刷新令牌轮换，书架按名字分开。"""

import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from ainovel.entry.auth import AuthError, AuthStore
from ainovel.entry.web import Accounts, _handler


def _store(tmp_path: Path, **kwargs) -> AuthStore:
    options = {"attempts": 8, "window": 600, "access_ttl": 60, "refresh_ttl": 3600, "n": 2**10}
    options.update(kwargs)
    return AuthStore(tmp_path, **options)


def test_register_hides_the_password_and_issues_two_tokens(tmp_path: Path):
    store = _store(tmp_path)
    tokens = store.register("夜里", "correct-horse", "local")
    assert tokens.username == "夜里"
    assert tokens.access_token.count(".") == 2
    assert tokens.refresh_token.count(".") == 2
    assert tokens.access_token != tokens.refresh_token
    stored = (tmp_path / "users.json").read_text(encoding="utf-8")
    assert "correct-horse" not in stored
    assert store.authenticate(tokens.access_token)["username"] == "夜里"
    with pytest.raises(AuthError):
        store.authenticate(tokens.refresh_token)


def test_duplicate_name_and_short_password_are_refused(tmp_path: Path):
    store = _store(tmp_path)
    store.register("夜里", "correct-horse", "local")
    with pytest.raises(AuthError, match="已经有人") as duplicate:
        store.register("夜里", "another-pass", "local")
    assert duplicate.value.status == 409
    with pytest.raises(AuthError, match="8") as short:
        store.register("新名", "short", "local")
    assert short.value.status == 400


def test_unsigned_token_is_rejected(tmp_path: Path):
    store = _store(tmp_path)
    tokens = store.register("夜里", "correct-horse", "local")
    header, body, _signature = tokens.access_token.split(".")
    forged = f"{header}.{body}.aaa"
    with pytest.raises(AuthError):
        store.authenticate(forged)


def test_expired_access_token_can_be_refreshed_once(tmp_path: Path):
    now = {"t": 1_700_000_000}
    store = _store(tmp_path, clock=lambda: now["t"], access_ttl=10, refresh_ttl=100)
    tokens = store.register("夜里", "correct-horse", "local")
    now["t"] += 10
    with pytest.raises(AuthError, match="过期"):
        store.authenticate(tokens.access_token)
    renewed = store.refresh(tokens.refresh_token)
    assert store.authenticate(renewed.access_token)["id"] == tokens.user_id
    with pytest.raises(AuthError, match="失效"):
        store.refresh(tokens.refresh_token)
    with pytest.raises(AuthError, match="失效"):
        store.refresh(renewed.refresh_token)


def test_failures_lock_the_client_until_the_window_passes(tmp_path: Path):
    now = {"t": 1_700_000_000}
    store = _store(tmp_path, clock=lambda: now["t"], attempts=2, window=30)
    store.register("夜里", "correct-horse", "local")
    with pytest.raises(AuthError, match="不对"):
        store.login("夜里", "wrong-pass", "local")
    with pytest.raises(AuthError, match="不对"):
        store.login("夜里", "wrong-pass", "local")
    with pytest.raises(AuthError, match="过一会儿") as locked:
        store.login("夜里", "correct-horse", "local")
    assert locked.value.status == 429
    now["t"] += 31
    assert store.login("夜里", "correct-horse", "local").username == "夜里"


def test_logout_and_password_change_drop_old_tokens(tmp_path: Path):
    store = _store(tmp_path)
    tokens = store.register("夜里", "correct-horse", "local")
    store.logout(tokens.access_token, "")
    with pytest.raises(AuthError):
        store.authenticate(tokens.access_token)
    fresh = store.login("夜里", "correct-horse", "local")
    changed = store.change_password(fresh.access_token, "correct-horse", "林舟", "another-pass")
    assert changed.username == "林舟"
    with pytest.raises(AuthError):
        store.authenticate(fresh.access_token)
    assert store.authenticate(changed.access_token)["username"] == "林舟"


@pytest.fixture
def studio(tmp_path: Path):
    auth = _store(tmp_path, attempts=3)
    accounts = Accounts(tmp_path)
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        _handler(accounts, auth, frozenset({"http://127.0.0.1:5173"})),
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        accounts.shutdown()
        thread.join(timeout=3)


def _call(httpd, method, path, body=None, token="", cookie="", origin="", site=""):
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
    headers = {}
    raw = None
    if body is not None:
        raw = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if cookie:
        headers["Cookie"] = cookie
    if origin:
        headers["Origin"] = origin
    if site:
        headers["Sec-Fetch-Site"] = site
    connection.request(method, path, body=raw, headers=headers)
    response = connection.getresponse()
    payload = response.read()
    status = response.status
    set_cookie = response.getheader("Set-Cookie") or ""
    connection.close()
    return status, payload, set_cookie


def _cookie(set_cookie: str) -> str:
    return set_cookie.split(";", 1)[0]


def test_api_requires_a_bearer_and_does_not_serve_the_page(studio):
    status, payload, _ = _call(studio, "GET", "/api/library")
    assert status == 401
    assert "先登录" in payload.decode("utf-8")
    page, html, _ = _call(studio, "GET", "/")
    assert page == 404
    assert "没有这个接口" in html.decode("utf-8")


def test_register_login_and_refresh_cookie(studio, tmp_path: Path):
    status, payload, set_cookie = _call(studio, "POST", "/api/register", {"username": "夜里", "password": "correct-horse"})
    assert status == 200
    body = json.loads(payload)
    assert body["token_type"] == "bearer"
    assert body["access_token"].count(".") == 2
    assert body["refresh_token"].count(".") == 2
    assert "HttpOnly" in set_cookie
    assert "Path=/api" in set_cookie
    assert "correct-horse" not in (tmp_path / "users.json").read_text(encoding="utf-8")

    library, listed, _ = _call(studio, "GET", "/api/library", token=body["access_token"])
    assert library == 200
    assert json.loads(listed)["books"] == []

    refused, _, refused_cookie = _call(studio, "POST", "/api/login", {"username": "夜里", "password": "wrong-pass"})
    assert refused == 401
    assert refused_cookie == ""

    refreshed, renewed, replacement = _call(studio, "POST", "/api/refresh", {}, cookie=_cookie(set_cookie))
    assert refreshed == 200
    new_body = json.loads(renewed)
    assert new_body["access_token"] != body["access_token"]
    assert "HttpOnly" in replacement
    stale, _, _ = _call(studio, "POST", "/api/refresh", {"refresh_token": body["refresh_token"]})
    assert stale == 401

    left, _, cleared = _call(studio, "POST", "/api/logout", {}, token=new_body["access_token"])
    assert left == 200
    assert "Max-Age=0" in cleared
    again, _, _ = _call(studio, "GET", "/api/library", token=new_body["access_token"])
    assert again == 401


def test_saved_model_stays_on_the_account(studio, tmp_path: Path):
    status, payload, _ = _call(studio, "POST", "/api/register", {"username": "夜里", "password": "correct-horse"})
    assert status == 200
    token = json.loads(payload)["access_token"]
    saved_status, saved_body, _ = _call(
        studio,
        "POST",
        "/api/model",
        {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-secret-value", "api_base": "", "style": "fantasy"},
        token=token,
    )
    assert saved_status == 200
    saved = json.loads(saved_body)
    assert saved["username"] == "夜里"
    assert saved["ready"] is True
    assert "sk-test-secret-value" not in saved_body.decode("utf-8")
    again, again_body, _ = _call(studio, "GET", "/api/model", token=token)
    assert again == 200
    loaded = json.loads(again_body)
    assert loaded["model"] == "gpt-4.1"
    assert loaded["style"] == "fantasy"
    assert loaded["username"] == "夜里"
    assert loaded["api_key_set"] is True
    configs = list((tmp_path / "accounts").glob("*/config.json"))
    assert len(configs) == 1
    assert json.loads(configs[0].read_text(encoding="utf-8"))["api_key"] == "sk-test-secret-value"


def test_two_accounts_do_not_share_a_shelf(studio, tmp_path: Path):
    book = tmp_path / "book"
    book.mkdir()
    first_status, first_payload, _ = _call(studio, "POST", "/api/register", {"username": "夜里", "password": "correct-horse"})
    second_status, second_payload, _ = _call(studio, "POST", "/api/register", {"username": "林舟", "password": "another-pass"})
    assert first_status == 200
    assert second_status == 200
    first = json.loads(first_payload)["access_token"]
    second = json.loads(second_payload)["access_token"]
    attached, _, _ = _call(studio, "POST", "/api/library", {"directory": str(book)}, token=first)
    assert attached == 200
    own, own_body, _ = _call(studio, "GET", "/api/library", token=first)
    other, other_body, _ = _call(studio, "GET", "/api/library", token=second)
    assert own == 200
    assert json.loads(own_body)["books"][0]["directory"] == str(book.resolve())
    assert other == 200
    assert json.loads(other_body)["books"] == []


def test_configured_frontend_origin_can_register(studio):
    status, payload, cookie = _call(
        studio,
        "POST",
        "/api/register",
        {"username": "夜里", "password": "correct-horse"},
        origin="http://127.0.0.1:5173",
    )
    assert status == 200
    assert "access_token" in payload.decode("utf-8")
    assert "HttpOnly" in cookie


def test_cross_site_register_is_rejected(studio):
    status, payload, cookie = _call(
        studio,
        "POST",
        "/api/register",
        {"username": "夜里", "password": "correct-horse"},
        origin="http://evil.test",
    )
    assert status == 403
    assert "跨站" in payload.decode("utf-8")
    assert cookie == ""


def test_repeated_login_failures_get_a_pause(studio):
    assert _call(studio, "POST", "/api/register", {"username": "夜里", "password": "correct-horse"})[0] == 200
    for _ in range(3):
        status, _, _ = _call(studio, "POST", "/api/login", {"username": "夜里", "password": "wrong-pass"})
        assert status == 401
    status, payload, _ = _call(studio, "POST", "/api/login", {"username": "夜里", "password": "correct-horse"})
    assert status == 429
    assert "过一会儿" in payload.decode("utf-8")
