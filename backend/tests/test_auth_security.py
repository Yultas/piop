import asyncio
import os
import sys
import uuid
import httpx
import pytest
from fastapi.testclient import TestClient

# Ensure backend package can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.app import ratelimit
from backend.app.main import app
from backend.app.config import settings

@pytest.fixture
def c():
    """Fresh client (own cookie jar, runs lifespan) with empty rate-limit state."""
    ratelimit.ip_limiter.clear()
    ratelimit.account_limiter.clear()
    with TestClient(app) as client:
        yield client
    ratelimit.ip_limiter.clear()
    ratelimit.account_limiter.clear()

def admin_login(c):
    return c.post("/api/auth/login", json={
        "username": settings.SUPERADMIN_USERNAME,
        "password": settings.SUPERADMIN_PASSWORD
    })

def test_login_sets_http_only_session_cookie(c):
    res = admin_login(c)
    assert res.status_code == 200
    header = res.headers["set-cookie"]
    lower = header.lower()
    attrs = {part.strip().split("=")[0].lower() for part in header.split(";")}
    assert header.startswith("piop_session=")
    assert "httponly" in attrs
    assert "samesite=strict" in lower
    assert "path=/api" in lower
    assert "secure" not in attrs

def test_cookie_only_auth(c):
    assert admin_login(c).status_code == 200
    res = c.get("/api/auth/me")
    assert res.status_code == 200

def test_cookie_auth_requires_csrf_header_on_unsafe_methods(c):
    assert admin_login(c).status_code == 200
    res = c.post("/api/workspaces", json={"name": "x"})
    assert res.status_code == 403
    assert res.json()["detail"] == "auth.csrf"

    res = c.post("/api/workspaces", json={"name": "x"}, headers={"X-Piop-CSRF": "1"})
    assert res.status_code != 403

def test_logout_clears_session(c):
    assert admin_login(c).status_code == 200
    res = c.post("/api/auth/logout")
    assert res.status_code == 200
    res = c.get("/api/auth/me")
    assert res.status_code == 401

def test_failed_logins_are_rate_limited(c):
    username = f"nobody-{uuid.uuid4()}"
    for _ in range(5):
        res = c.post("/api/auth/login", json={"username": username, "password": "wrong"})
        assert res.status_code == 401
    res = c.post("/api/auth/login", json={"username": username, "password": "wrong"})
    assert res.status_code == 429
    assert "retry-after" in res.headers

def test_bearer_header_takes_precedence_over_cookie(c):
    assert admin_login(c).status_code == 200
    res = c.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert res.status_code == 401

def test_concurrent_bad_logins_cannot_exceed_account_limit():
    """Requests in flight together must each reserve a slot before awaiting the DB."""
    username = f"nobody-{uuid.uuid4()}"
    body = {"username": username, "password": "wrong"}

    async def fire():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            results = await asyncio.gather(*(ac.post("/api/auth/login", json=body) for _ in range(20)))
        return [r.status_code for r in results]

    ratelimit.ip_limiter.clear()
    ratelimit.account_limiter.clear()
    try:
        with TestClient(app):
            codes = asyncio.run(fire())
    finally:
        ratelimit.ip_limiter.clear()
        ratelimit.account_limiter.clear()
    assert codes.count(401) == 5
    assert codes.count(429) == 15

def test_login_rejects_overlong_username(c):
    res = c.post("/api/auth/login", json={"username": "a" * 200, "password": "wrong"})
    assert res.status_code == 422

def test_invite_claim_password_guesses_count_against_account_limit(c):
    assert admin_login(c).status_code == 200
    ws = c.post("/api/workspaces", json={"name": f"ws-{uuid.uuid4().hex[:6]}", "storage_quota_mb": 5},
                headers={"X-Piop-CSRF": "1"})
    assert ws.status_code == 201
    inv = c.post("/api/invites", json={"workspace_id": ws.json()["id"], "target_role": "member",
                                       "expires_in_days": 3},
                 headers={"X-Piop-CSRF": "1"})
    assert inv.status_code == 200
    token = inv.json()["token"]

    # Existing user, wrong password: each guess is a 401 until the per-account window fills.
    codes = [
        c.post(f"/api/invites/{token}/claim", json={
            "username": settings.SUPERADMIN_USERNAME,
            "password": "wrong",
            "raw_fingerprint": "FP_GUESS",
        }).status_code
        for _ in range(6)
    ]
    assert codes == [401, 401, 401, 401, 401, 429]
