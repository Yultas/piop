import json
import os
import sys
import uuid
import pytest
from fastapi.testclient import TestClient

# Ensure backend package can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.app.main import app
from backend.app.config import settings
from backend.app.ai.tools import TOOLS_BY_NAME

state: dict = {}

@pytest.fixture(scope="module")
def c():
    """Run startup (schema creation, superadmin seed) so tests work on an empty database."""
    with TestClient(app) as client:
        yield client

def jwt_headers(c) -> dict:
    res = c.post("/api/auth/login", json={
        "username": settings.SUPERADMIN_USERNAME,
        "password": settings.SUPERADMIN_PASSWORD,
    })
    return {"Authorization": f"Bearer {res.json()['access_token']}"}

def api_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

def rpc(c, body, headers):
    return c.post("/api/mcp", json=body, headers=headers)

def tool_call(c, name, arguments, headers):
    res = rpc(c, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": name, "arguments": arguments}}, headers)
    assert res.status_code == 200
    return res.json()["result"]

def test_01_create_token_and_list(c):
    """A token is created with a JWT login; only its prefix is listed, never the full token."""
    state["jwt"] = jwt_headers(c)
    res = c.post("/api/auth/tokens", json={"name": "test agent"}, headers=state["jwt"])
    assert res.status_code == 201
    data = res.json()
    assert data["token"].startswith("piop_")
    state["token"] = data["token"]
    state["token_id"] = data["id"]

    items = c.get("/api/auth/tokens", headers=state["jwt"]).json()
    mine = [t for t in items if t["id"] == data["id"]]
    assert len(mine) == 1
    assert mine[0]["prefix"] == data["token"][:12]
    assert mine[0]["last_used_at"] is None
    assert "token" not in mine[0]

def test_02_api_token_bearer_works_and_sets_last_used(c):
    res = c.get("/api/auth/me", headers=api_headers(state["token"]))
    assert res.status_code == 200
    items = c.get("/api/auth/tokens", headers=state["jwt"]).json()
    mine = [t for t in items if t["id"] == state["token_id"]]
    assert mine[0]["last_used_at"] is not None

def test_03_api_token_cannot_manage_tokens(c):
    res = c.get("/api/auth/tokens", headers=api_headers(state["token"]))
    assert res.status_code == 403
    assert res.json()["detail"] == "auth.session_required"
    res = c.post("/api/auth/tokens", json={"name": "minted"}, headers=api_headers(state["token"]))
    assert res.status_code == 403
    assert res.json()["detail"] == "auth.session_required"

def test_04_deleted_token_is_revoked(c):
    created = c.post("/api/auth/tokens", json={"name": "to revoke"}, headers=state["jwt"]).json()
    assert c.get("/api/auth/me", headers=api_headers(created["token"])).status_code == 200
    res = c.delete(f"/api/auth/tokens/{created['id']}", headers=state["jwt"])
    assert res.status_code == 204
    res = c.get("/api/auth/me", headers=api_headers(created["token"]))
    assert res.status_code == 401
    assert res.json()["detail"] == "auth.invalid_token"

def test_05_initialize_and_notification(c):
    res = rpc(c, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                             "clientInfo": {"name": "test", "version": "0"}}}, api_headers(state["token"]))
    assert res.status_code == 200
    result = res.json()["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "piop"
    assert "tools" in result["capabilities"]

    res = rpc(c, {"jsonrpc": "2.0", "method": "notifications/initialized"}, api_headers(state["token"]))
    assert res.status_code == 202
    assert res.content == b""

def test_06_tools_list_is_not_mutated(c):
    res = rpc(c, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, api_headers(state["token"]))
    tools = {t["name"]: t for t in res.json()["result"]["tools"]}
    assert "list_workspaces" in tools
    assert "create_task" in tools
    create = tools["create_task"]
    assert create["inputSchema"]["required"][0] == "workspace_id"
    assert create["inputSchema"]["properties"]["workspace_id"]["type"] == "integer"
    assert create["annotations"] == {"readOnlyHint": False, "destructiveHint": False}
    assert tools["delete_task"]["annotations"]["destructiveHint"] is True
    # The shared assistant definition must stay as it was.
    assert "workspace_id" not in TOOLS_BY_NAME["create_task"].parameters["properties"]
    assert "workspace_id" not in TOOLS_BY_NAME["create_task"].parameters["required"]

def test_07_list_workspaces(c):
    ws = c.post("/api/workspaces", json={"name": "MCP test workspace"}, headers=state["jwt"])
    assert ws.status_code == 201
    state["ws_id"] = ws.json()["id"]
    result = tool_call(c, "list_workspaces", {}, api_headers(state["token"]))
    assert result["isError"] is False
    ids = [w["id"] for w in json.loads(result["content"][0]["text"])]
    assert state["ws_id"] in ids

def test_08_create_task_and_see_it_in_app(c):
    result = tool_call(c, "create_task", {"workspace_id": state["ws_id"], "title": "Ship the MCP endpoint"},
                       api_headers(state["token"]))
    assert result["isError"] is False
    tasks = c.get(f"/api/workspaces/{state['ws_id']}/tasks", headers=state["jwt"])
    assert "Ship the MCP endpoint" in tasks.text

def test_09_delete_is_disabled_by_default(c):
    result = tool_call(c, "delete_task", {"workspace_id": state["ws_id"], "task_id": 1},
                       api_headers(state["token"]))
    assert result["isError"] is True
    assert "disabled" in result["content"][0]["text"]

def test_10_unknown_workspace_is_denied(c):
    result = tool_call(c, "create_task", {"workspace_id": 999999, "title": "nope"}, api_headers(state["token"]))
    assert result["isError"] is True
    assert "not found or access denied" in result["content"][0]["text"]

def test_11_protocol_errors_and_auth(c):
    res = rpc(c, {"jsonrpc": "2.0", "id": 3, "method": "resources/list"}, api_headers(state["token"]))
    assert res.json()["error"]["code"] == -32601
    res = rpc(c, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                  "params": {"name": "no_such_tool", "arguments": {}}}, api_headers(state["token"]))
    assert res.json()["error"]["code"] == -32602
    c.cookies.clear()
    res = c.post("/api/mcp", json={"jsonrpc": "2.0", "id": 5, "method": "ping"})
    assert res.status_code == 401

def test_12_get_is_not_allowed(c):
    assert c.get("/api/mcp", headers=api_headers(state["token"])).status_code == 405

def make_member(c, admin: dict, ws_id: int, label: str) -> tuple[dict, str]:
    """Claim a fresh invite as a regular user; returns (session headers, username)."""
    invite = c.post("/api/invites", json={"workspace_id": ws_id, "target_role": "member", "expires_in_days": 3},
                    headers=admin).json()["token"]
    username = f"mcp_{label}_{uuid.uuid4().hex[:8]}"
    res = c.post(f"/api/invites/{invite}/claim", json={
        "username": username,
        "password": "SecureMcpPass_2026!",
        "raw_fingerprint": f"EINK_MCP_{uuid.uuid4().hex}",
    })
    assert res.status_code == 200
    return api_headers(res.json()["access_token"]), username

def user_id_of(c, admin: dict, username: str) -> int:
    return next(u["id"] for u in c.get("/api/admin/users", headers=admin).json() if u["username"] == username)

def test_13_deleted_user_token_does_not_reach_next_user(c):
    """Deleting a user revokes their API tokens; a new user reusing the freed id must not inherit them."""
    admin = state["jwt"]
    member, username = make_member(c, admin, state["ws_id"], "doomed")
    member_id = user_id_of(c, admin, username)
    token = c.post("/api/auth/tokens", json={"name": "doomed"}, headers=member).json()["token"]
    assert c.get("/api/auth/me", headers=api_headers(token)).status_code == 200

    assert c.delete(f"/api/admin/users/{member_id}", headers=admin).status_code == 200
    _, successor = make_member(c, admin, state["ws_id"], "successor")
    # The successor is the newest row, so SQLite hands it the id just freed: the case the token must not reach
    assert user_id_of(c, admin, successor) == member_id
    res = c.get("/api/auth/me", headers=api_headers(token))
    assert res.status_code == 401
    assert res.json()["detail"] == "auth.invalid_token"

def test_14_membership_limits_list_and_access(c):
    admin = state["jwt"]
    ws_b = c.post("/api/workspaces", json={"name": "MCP other workspace"}, headers=admin).json()["id"]
    member, _ = make_member(c, admin, state["ws_id"], "member")
    token = c.post("/api/auth/tokens", json={"name": "member agent"}, headers=member).json()["token"]

    listed = tool_call(c, "list_workspaces", {}, api_headers(token))
    ids = [w["id"] for w in json.loads(listed["content"][0]["text"])]
    assert state["ws_id"] in ids
    assert ws_b not in ids

    denied = tool_call(c, "list_tasks", {"workspace_id": ws_b}, api_headers(token))
    assert denied["isError"] is True
    assert "not found or access denied" in denied["content"][0]["text"]
    allowed = tool_call(c, "list_tasks", {"workspace_id": state["ws_id"]}, api_headers(token))
    assert allowed["isError"] is False

def test_15_batch_survives_a_tool_error(c):
    """A failed tool call rolls the session back; later messages in the same batch must still be answered."""
    batch = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "update_task", "arguments": {"workspace_id": state["ws_id"], "task_id": 999999}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "list_tasks", "arguments": {"workspace_id": state["ws_id"]}}},
    ]
    res = rpc(c, batch, api_headers(state["token"]))
    assert res.status_code == 200
    first, second = res.json()
    assert first["id"] == 1 and first["result"]["isError"] is True
    assert second["id"] == 2 and second["result"]["isError"] is False

def test_16_oversized_workspace_id_is_denied(c):
    result = tool_call(c, "list_tasks", {"workspace_id": 10**30}, api_headers(state["token"]))
    assert result["isError"] is True
    assert "not found or access denied" in result["content"][0]["text"]

def test_17_client_response_object_gets_202(c):
    res = rpc(c, {"jsonrpc": "2.0", "id": 7, "result": {}}, api_headers(state["token"]))
    assert res.status_code == 202
    assert res.content == b""
    res = rpc(c, {"jsonrpc": "2.0", "id": 8, "error": {"code": -32000, "message": "x"}}, api_headers(state["token"]))
    assert res.status_code == 202
    assert res.content == b""

def test_18_deleted_user_session_does_not_reach_next_user(c):
    """A login session (JWT) of a deleted user must not work for a new user that gets the freed id."""
    admin = state["jwt"]
    member, username = make_member(c, admin, state["ws_id"], "gone")
    member_id = user_id_of(c, admin, username)
    assert c.get("/api/auth/me", headers=member).status_code == 200

    assert c.delete(f"/api/admin/users/{member_id}", headers=admin).status_code == 200
    successor_headers, successor = make_member(c, admin, state["ws_id"], "heir")
    assert user_id_of(c, admin, successor) == member_id
    res = c.get("/api/auth/me", headers=member)
    assert res.status_code == 401
    assert res.json()["detail"] == "auth.invalid_token"
    assert c.get("/api/auth/me", headers=successor_headers).status_code == 200

def test_19_claim_accepts_large_canvas_fingerprint(c):
    """A canvas data URL often exceeds 8 KiB, depending on the client's fonts; the claim must still work."""
    admin = state["jwt"]
    invite = c.post("/api/invites", json={"workspace_id": state["ws_id"], "target_role": "member", "expires_in_days": 3},
                    headers=admin).json()["token"]
    res = c.post(f"/api/invites/{invite}/claim", json={
        "username": f"mcp_bigfp_{uuid.uuid4().hex[:8]}",
        "password": "SecureMcpPass_2026!",
        "raw_fingerprint": "canvas:data:image/png;base64," + "A" * 20000,
    })
    assert res.status_code == 200
