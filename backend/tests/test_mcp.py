import json
import os
import sys
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
