import os
import stat
import sys
import uuid
import pytest
from fastapi.testclient import TestClient

# Ensure backend package can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.app.main import app
from backend.app.config import settings, Settings, ensure_secrets, INSECURE_SECRETS

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def app_lifespan():
    """Run startup (schema creation, superadmin seed) so tests work on an empty database."""
    with client:
        yield

def admin_headers():
    login_res = client.post("/api/auth/login", json={
        "username": settings.SUPERADMIN_USERNAME,
        "password": settings.SUPERADMIN_PASSWORD
    })
    return {"Authorization": f"Bearer {login_res.json()['access_token']}"}

def test_01_superadmin_login():
    """Test superadmin authentication via /api/auth/login."""
    # 1. Invalid credentials
    bad_res = client.post("/api/auth/login", json={
        "username": settings.SUPERADMIN_USERNAME,
        "password": "wrongpassword!"
    })
    assert bad_res.status_code == 401
    assert bad_res.json()["detail"] == "auth.invalid_credentials"

    # 2. Valid credentials
    good_res = client.post("/api/auth/login", json={
        "username": settings.SUPERADMIN_USERNAME,
        "password": settings.SUPERADMIN_PASSWORD
    })
    assert good_res.status_code == 200
    data = good_res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["username"] == settings.SUPERADMIN_USERNAME
    assert data["user"]["is_global_admin"] is True

    # 3. /api/auth/me with bearer token
    token = data["access_token"]
    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["username"] == settings.SUPERADMIN_USERNAME

def test_02_admin_create_workspace():
    """Test workspace creation by administrator."""
    # Login admin
    login_res = client.post("/api/auth/login", json={
        "username": settings.SUPERADMIN_USERNAME,
        "password": settings.SUPERADMIN_PASSWORD
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    ws_name = f"Test Workspace {uuid.uuid4().hex[:6]}"
    res = client.post("/api/workspaces", json={
        "name": ws_name,
        "description": "Integration test workspace",
        "storage_quota_mb": 10
    }, headers=headers)
    
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == ws_name
    assert data["storage_quota_bytes"] == 10 * 1024 * 1024
    assert "id" in data

    # Verify listing
    list_res = client.get("/api/workspaces", headers=headers)
    assert list_res.status_code == 200
    names = [w["name"] for w in list_res.json()]
    assert ws_name in names

def test_03_invite_device_fingerprint_binding():
    """
    Test invite creation and device fingerprint hardware binding:
    - 1st login with DEV1 succeeds and binds the device.
    - 2nd login with DEV1 succeeds (reconnected).
    - Login attempt with DEV2 fails with 403 Device Locked.
    """
    login_res = client.post("/api/auth/login", json={
        "username": settings.SUPERADMIN_USERNAME,
        "password": settings.SUPERADMIN_PASSWORD
    })
    admin_token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Create workspace
    ws_res = client.post("/api/workspaces", json={
        "name": f"Secure Device WS {uuid.uuid4().hex[:6]}",
        "storage_quota_mb": 5
    }, headers=headers)
    assert ws_res.status_code == 201
    ws_id = ws_res.json()["id"]

    # 2. Create invite
    inv_res = client.post("/api/invites", json={
        "workspace_id": ws_id,
        "target_role": "member",
        "expires_in_days": 3
    }, headers=headers)
    assert inv_res.status_code == 200
    invite_token = inv_res.json()["token"]

    # 3. Inspect invite
    info_res = client.get(f"/api/invites/{invite_token}")
    assert info_res.status_code == 200
    assert info_res.json()["status"] == "ISSUED"
    assert info_res.json()["is_claimed"] is False

    dev1_fingerprint = "EINK_DEV1_CANVAS_FINGERPRINT_HASH_AA11"
    dev2_fingerprint = "EINK_DEV2_ROGUE_DEVICE_FINGERPRINT_BB22"
    member_username = f"user_{uuid.uuid4().hex[:8]}"
    member_password = "SecureMemberPass_2026!"

    # 4. First claim with DEV1 -> Success, binds fingerprint
    claim1_res = client.post(f"/api/invites/{invite_token}/claim", json={
        "username": member_username,
        "password": member_password,
        "raw_fingerprint": dev1_fingerprint
    })
    assert claim1_res.status_code == 200
    claim1_data = claim1_res.json()
    assert claim1_data["message"] == "claimed_and_bound"
    assert "access_token" in claim1_data

    # 5. Subsequent login with SAME DEV1 -> Success
    claim2_res = client.post(f"/api/invites/{invite_token}/claim", json={
        "username": member_username,
        "password": member_password,
        "raw_fingerprint": dev1_fingerprint
    })
    assert claim2_res.status_code == 200
    claim2_data = claim2_res.json()
    assert claim2_data["message"] == "reconnected"
    assert "access_token" in claim2_data

    # 6. Attempt login from DIFFERENT DEV2 -> 403 Forbidden (Device Locked)
    claim3_res = client.post(f"/api/invites/{invite_token}/claim", json={
        "username": member_username,
        "password": member_password,
        "raw_fingerprint": dev2_fingerprint
    })
    assert claim3_res.status_code == 403
    assert claim3_res.json()["detail"] == "auth.invite.device_locked"

def test_04_file_upload_and_quota_limit():
    """
    Test file upload and enforcement of disk quota limits:
    - Normal upload within quota succeeds.
    - Exceeding quota returns 413 Payload Too Large.
    """
    login_res = client.post("/api/auth/login", json={
        "username": settings.SUPERADMIN_USERNAME,
        "password": settings.SUPERADMIN_PASSWORD
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create workspace with exactly 1 MB quota
    ws_res = client.post("/api/workspaces", json={
        "name": f"Quota Test WS {uuid.uuid4().hex[:6]}",
        "storage_quota_mb": 1
    }, headers=headers)
    assert ws_res.status_code == 201
    ws_id = ws_res.json()["id"]

    # Upload small file: 100 KB
    file_content_100k = b"A" * (100 * 1024)
    upload1_res = client.post(
        f"/api/workspaces/{ws_id}/files",
        files={"file": ("test_doc.txt", file_content_100k, "text/plain")},
        headers=headers
    )
    assert upload1_res.status_code == 201
    file1_data = upload1_res.json()
    assert file1_data["file_size_bytes"] == 100 * 1024
    assert file1_data["used_storage_bytes"] == 100 * 1024

    # Verify quota status via file list
    list_files_res = client.get(f"/api/workspaces/{ws_id}/files", headers=headers)
    assert list_files_res.status_code == 200
    files_info = list_files_res.json()
    assert len(files_info["files"]) == 1
    assert files_info["used_storage_bytes"] == 100 * 1024

    # Attempt to upload large file exceeding 1 MB total: 1.2 MB file
    oversized_content = b"B" * (1200 * 1024)
    upload2_res = client.post(
        f"/api/workspaces/{ws_id}/files",
        files={"file": ("huge_file.dat", oversized_content, "application/octet-stream")},
        headers=headers
    )
    assert upload2_res.status_code == 413
    assert "limit_exceeded" in upload2_res.json()["detail"]

    # Delete first file and check quota recovery
    del_res = client.delete(f"/api/workspaces/{ws_id}/files/{file1_data['id']}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["used_storage_bytes"] == 0

def test_05_channel_message_and_task_conversion():
    """
    Test sending a channel message and converting it to a task:
    - POST channel message.
    - POST /api/workspaces/:id/tasks/from-message converts message to task.
    """
    login_res = client.post("/api/auth/login", json={
        "username": settings.SUPERADMIN_USERNAME,
        "password": settings.SUPERADMIN_PASSWORD
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create workspace
    ws_res = client.post("/api/workspaces", json={
        "name": f"Tasks WS {uuid.uuid4().hex[:6]}",
        "storage_quota_mb": 5
    }, headers=headers)
    assert ws_res.status_code == 201
    ws_id = ws_res.json()["id"]

    # Get channels (general channel is auto-created)
    channels_res = client.get(f"/api/workspaces/{ws_id}/channels", headers=headers)
    assert channels_res.status_code == 200
    channels = channels_res.json()
    assert len(channels) >= 1
    channel_id = channels[0]["id"]

    # Post message in channel
    msg_text = "Urgent: prepare high contrast diagrams for E-Ink screen"
    send_res = client.post(
        f"/api/workspaces/{ws_id}/channels/{channel_id}/messages",
        json={"content": msg_text},
        headers=headers
    )
    assert send_res.status_code == 201
    msg_data = send_res.json()
    msg_id = msg_data["id"]
    assert msg_data["content"] == msg_text

    # Convert message to task
    task_res = client.post(
        f"/api/workspaces/{ws_id}/tasks/from-message",
        json={
            "message_id": msg_id,
            "title": "Prepare E-Ink Diagrams",
            "priority": "high"
        },
        headers=headers
    )
    assert task_res.status_code == 201
    task_data = task_res.json()
    assert task_data["origin_message_id"] == msg_id
    assert task_data["title"] == "Prepare E-Ink Diagrams"
    assert task_data["priority"] == "high"
    assert task_data["status"] == "todo"
    assert msg_text in task_data["description"]
    task_id = task_data["id"]

    # Update task status to in_progress
    patch_res = client.patch(
        f"/api/workspaces/{ws_id}/tasks/{task_id}/status",
        json={"status": "in_progress"},
        headers=headers
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "in_progress"

    # Verify task in workspace tasks list
    list_tasks = client.get(f"/api/workspaces/{ws_id}/tasks", headers=headers)
    assert list_tasks.status_code == 200
    tasks = list_tasks.json()
    assert any(t["id"] == task_id and t["status"] == "in_progress" for t in tasks)

def test_06_typst_compile_to_svg():
    """
    Test Typst code compilation via /api/typst/compile into vector SVG.
    """
    typst_code = """
    #set page(width: auto, height: auto, margin: 1cm)
    = E-Ink Technical Specification

    The quick brown fox jumps over the lazy dog.

    $ E = m c^2 $
    """
    res = client.post("/api/typst/compile", json={
        "code": typst_code,
        "format": "svg"
    }, headers=admin_headers())
    assert res.status_code == 200
    data = res.json()
    assert data["format"] == "svg"
    svg_output = data["result"]
    assert "<svg" in svg_output
    assert "</svg>" in svg_output

def test_07_admin_delete_workspace():
    """Test that deleting a workspace removes it together with its channels, messages and tasks."""
    login_res = client.post("/api/auth/login", json={
        "username": settings.SUPERADMIN_USERNAME,
        "password": settings.SUPERADMIN_PASSWORD
    })
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    ws_res = client.post("/api/workspaces", json={
        "name": f"Delete WS {uuid.uuid4().hex[:6]}",
        "storage_quota_mb": 5
    }, headers=headers)
    ws_id = ws_res.json()["id"]

    # Populate with a message, a thread reply and a task created from the message
    channel_id = client.get(f"/api/workspaces/{ws_id}/channels", headers=headers).json()[0]["id"]
    msg_id = client.post(
        f"/api/workspaces/{ws_id}/channels/{channel_id}/messages",
        json={"content": "to be deleted"},
        headers=headers
    ).json()["id"]
    client.post(
        f"/api/workspaces/{ws_id}/channels/{channel_id}/messages",
        json={"content": "reply", "thread_parent_id": msg_id},
        headers=headers
    )
    client.post(
        f"/api/workspaces/{ws_id}/tasks/from-message",
        json={"message_id": msg_id, "title": "Doomed task"},
        headers=headers
    )

    del_res = client.delete(f"/api/admin/workspaces/{ws_id}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True

    ids = [w["id"] for w in client.get("/api/admin/workspaces", headers=headers).json()]
    assert ws_id not in ids

    # Deleting again reports not found
    again = client.delete(f"/api/admin/workspaces/{ws_id}", headers=headers)
    assert again.status_code == 404

def test_08_admin_delete_user():
    """Test deleting a user: messages go away, tasks stay, the invite can no longer be reused."""
    login_res = client.post("/api/auth/login", json={
        "username": settings.SUPERADMIN_USERNAME,
        "password": settings.SUPERADMIN_PASSWORD
    })
    admin_data = login_res.json()
    headers = {"Authorization": f"Bearer {admin_data['access_token']}"}

    # Self-deletion is refused
    self_res = client.delete(f"/api/admin/users/{admin_data['user']['id']}", headers=headers)
    assert self_res.status_code == 400
    assert self_res.json()["detail"] == "admin.cannot_delete_self"

    ws_id = client.post("/api/workspaces", json={
        "name": f"User Delete WS {uuid.uuid4().hex[:6]}",
        "storage_quota_mb": 5
    }, headers=headers).json()["id"]
    invite_token = client.post("/api/invites", json={
        "workspace_id": ws_id,
        "target_role": "member",
        "expires_in_days": 3
    }, headers=headers).json()["token"]

    member_username = f"user_{uuid.uuid4().hex[:8]}"
    member_password = "SecureMemberPass_2026!"
    fingerprint = "EINK_DELETE_USER_FINGERPRINT_CC33"
    claim_res = client.post(f"/api/invites/{invite_token}/claim", json={
        "username": member_username,
        "password": member_password,
        "raw_fingerprint": fingerprint
    })
    member_headers = {"Authorization": f"Bearer {claim_res.json()['access_token']}"}

    # Member writes a message, admin turns it into a task
    channel_id = client.get(f"/api/workspaces/{ws_id}/channels", headers=member_headers).json()[0]["id"]
    msg_id = client.post(
        f"/api/workspaces/{ws_id}/channels/{channel_id}/messages",
        json={"content": "member message"},
        headers=member_headers
    ).json()["id"]
    task_id = client.post(
        f"/api/workspaces/{ws_id}/tasks/from-message",
        json={"message_id": msg_id, "title": "Task from member"},
        headers=headers
    ).json()["id"]

    member_id = next(
        u["id"] for u in client.get("/api/admin/users", headers=headers).json()
        if u["username"] == member_username
    )
    del_res = client.delete(f"/api/admin/users/{member_id}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True

    usernames = [u["username"] for u in client.get("/api/admin/users", headers=headers).json()]
    assert member_username not in usernames

    # The member's token and device-bound invite stop working
    assert client.get("/api/auth/me", headers=member_headers).status_code == 401
    reuse = client.post(f"/api/invites/{invite_token}/claim", json={
        "username": member_username,
        "password": member_password,
        "raw_fingerprint": fingerprint
    })
    assert reuse.status_code == 400

    # The task survives without its origin message
    tasks = client.get(f"/api/workspaces/{ws_id}/tasks", headers=headers).json()
    task = next(t for t in tasks if t["id"] == task_id)
    assert task["origin_message_id"] is None

    assert client.delete(f"/api/admin/users/{member_id}", headers=headers).status_code == 404

def test_09_search_index():
    """Full-text search finds documents, tasks and messages and follows edits and deletes."""
    headers = admin_headers()
    ws_id = client.post("/api/workspaces", json={
        "name": f"Search WS {uuid.uuid4().hex[:6]}", "storage_quota_mb": 5
    }, headers=headers).json()["id"]

    doc_id = client.post(f"/api/workspaces/{ws_id}/documents", json={
        "title": "Квартальный бюджет", "doc_type": "doc",
        "content_raw": "Расходы на рекламу: 500 тысяч. Ёлка в офис."
    }, headers=headers).json()["id"]
    client.post(f"/api/workspaces/{ws_id}/tasks", json={"title": "Согласовать рекламу"}, headers=headers)

    def search(q):
        res = client.get(f"/api/workspaces/{ws_id}/ai/search", params={"q": q}, headers=headers)
        assert res.status_code == 200
        return res.json()

    hits = search("БЮДЖЕТ")
    assert hits[0]["kind"] == "document" and hits[0]["id"] == doc_id
    assert {h["kind"] for h in search("реклам")} == {"document", "task"}
    assert search("елка")[0]["id"] == doc_id  # ё folds into е

    client.put(f"/api/workspaces/{ws_id}/documents/{doc_id}", json={"content_raw": "Пусто"}, headers=headers)
    assert all(h["kind"] != "document" for h in search("реклам"))
    client.delete(f"/api/workspaces/{ws_id}/documents/{doc_id}", headers=headers)
    assert search("Квартальный") == []

    # Other workspaces never leak into results
    other_ws = client.post("/api/workspaces", json={"name": "Other", "storage_quota_mb": 5}, headers=headers).json()["id"]
    assert client.get(f"/api/workspaces/{other_ws}/ai/search", params={"q": "реклам"}, headers=headers).json() == []

class ScriptedLLM:
    """Stands in for the provider: returns queued replies and records what it was sent."""
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def __call__(self, cfg, messages, tools):
        self.calls.append({"messages": messages, "tools": [t["function"]["name"] for t in tools]})
        return self.replies.pop(0)

def tool_call(call_id, name, args):
    import json
    return {"content": None, "tool_calls": [{
        "id": call_id, "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}
    }]}

def test_10_ai_assistant_tools_and_confirmation(monkeypatch):
    """The assistant searches automatically, waits for approval on writes, and never gets disabled tools."""
    from backend.app.ai import llm
    headers = admin_headers()

    assert client.put("/api/admin/ai-settings", json={
        "enabled": True, "base_url": "http://fake-llm/v1", "model": "fake-model", "api_key": "sk-test-12345678"
    }, headers=headers).json()["configured"] is True
    stored = client.get("/api/admin/ai-settings", headers=headers).json()
    assert "api_key" not in stored and stored["api_key_hint"] == "…5678"

    ws_id = client.post("/api/workspaces", json={
        "name": f"AI WS {uuid.uuid4().hex[:6]}", "storage_quota_mb": 5
    }, headers=headers).json()["id"]
    client.post(f"/api/workspaces/{ws_id}/documents", json={
        "title": "План запуска", "doc_type": "doc", "content_raw": "Запуск в марте"
    }, headers=headers)
    base = f"/api/workspaces/{ws_id}/ai"

    fake = ScriptedLLM([
        tool_call("c1", "search_workspace", {"query": "запуск"}),
        tool_call("c2", "create_task", {"title": "Подготовить запуск", "priority": "high"}),
        {"content": "Задача создана.", "tool_calls": None},
    ])
    monkeypatch.setattr(llm, "chat_completion", fake)

    conv_id = client.post(f"{base}/conversations", json={}, headers=headers).json()["id"]
    res = client.post(f"{base}/conversations/{conv_id}/messages", json={"content": "Создай задачу по запуску"}, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["pending"] is True
    tool_rows = [m for m in data["messages"] if m["role"] == "tool"]
    assert tool_rows[0]["tool_name"] == "search_workspace" and tool_rows[0]["status"] == "done"
    assert "План запуска" in tool_rows[0]["content"]
    pending = tool_rows[1]
    assert pending["tool_name"] == "create_task" and pending["status"] == "pending"

    # Defaults: reads and writes offered, deletes withheld from the model
    assert "search_workspace" in fake.calls[0]["tools"] and "create_task" in fake.calls[0]["tools"]
    assert "delete_task" not in fake.calls[0]["tools"]

    # Nothing is written before approval, and new questions wait for the decision
    assert client.get(f"/api/workspaces/{ws_id}/tasks", headers=headers).json() == []
    assert client.post(f"{base}/conversations/{conv_id}/messages", json={"content": "ещё"}, headers=headers).status_code == 409

    res = client.post(f"{base}/conversations/{conv_id}/actions/{pending['id']}/approve", headers=headers)
    data = res.json()
    assert data["pending"] is False
    assert data["messages"][-1]["content"] == "Задача создана."
    tasks = client.get(f"/api/workspaces/{ws_id}/tasks", headers=headers).json()
    assert [t["title"] for t in tasks] == ["Подготовить запуск"]
    # The model saw the real tool result after approval
    assert any(m["role"] == "tool" and "Подготовить запуск" in m["content"] for m in fake.calls[-1]["messages"])

    # Rejection is reported to the model and nothing changes
    fake2 = ScriptedLLM([
        tool_call("c3", "update_task", {"task_id": tasks[0]["id"], "status": "done"}),
        {"content": "Хорошо, не меняю.", "tool_calls": None},
    ])
    monkeypatch.setattr(llm, "chat_completion", fake2)
    data = client.post(f"{base}/conversations/{conv_id}/messages", json={"content": "Закрой её"}, headers=headers).json()
    pending_id = next(m["id"] for m in data["messages"] if m["status"] == "pending")
    data = client.post(f"{base}/conversations/{conv_id}/actions/{pending_id}/reject", headers=headers).json()
    assert data["messages"][-1]["content"] == "Хорошо, не меняю."
    assert client.get(f"/api/workspaces/{ws_id}/tasks", headers=headers).json()[0]["status"] == "todo"

    # A disabled tool the model calls anyway is refused; "auto" runs without asking
    perms = client.put(f"{base}/permissions", json={"modes": {"create_task": "off", "update_task": "auto"}}, headers=headers)
    assert {p["action"]: p["mode"] for p in perms.json()}["create_task"] == "off"
    fake3 = ScriptedLLM([
        {"content": None, "tool_calls": [
            tool_call("c4", "create_task", {"title": "X"})["tool_calls"][0],
            tool_call("c5", "update_task", {"task_id": tasks[0]["id"], "status": "done"})["tool_calls"][0],
        ]},
        {"content": "Готово.", "tool_calls": None},
    ])
    monkeypatch.setattr(llm, "chat_completion", fake3)
    data = client.post(f"{base}/conversations/{conv_id}/messages", json={"content": "Закрой"}, headers=headers).json()
    statuses = {m["tool_name"]: m["status"] for m in data["messages"] if m["role"] == "tool"}
    assert statuses["create_task"] == "error" and statuses["update_task"] == "done"
    assert "create_task" not in fake3.calls[0]["tools"]
    assert client.get(f"/api/workspaces/{ws_id}/tasks", headers=headers).json()[0]["status"] == "done"

    # Objects of other workspaces are out of reach
    other_ws = client.post("/api/workspaces", json={"name": "Other AI", "storage_quota_mb": 5}, headers=headers).json()["id"]
    other_doc = client.post(f"/api/workspaces/{other_ws}/documents", json={
        "title": "Secret", "doc_type": "doc", "content_raw": "hidden"
    }, headers=headers).json()["id"]
    fake4 = ScriptedLLM([
        tool_call("c6", "read_document", {"document_id": other_doc}),
        {"content": "Не нашёл.", "tool_calls": None},
    ])
    monkeypatch.setattr(llm, "chat_completion", fake4)
    data = client.post(f"{base}/conversations/{conv_id}/messages", json={"content": "Прочитай"}, headers=headers).json()
    row = [m for m in data["messages"] if m["tool_name"] == "read_document"][-1]
    assert row["status"] == "error" and "hidden" not in row["content"]

    # Deleting the workspace removes its conversations too
    assert client.delete(f"/api/admin/workspaces/{ws_id}", headers=headers).status_code == 200

def test_11_folders_and_archive():
    """Folders nest, move and delete recursively; selections download as a zip with the folder structure."""
    import io
    import zipfile
    headers = admin_headers()
    ws_id = client.post("/api/workspaces", json={
        "name": f"Folders WS {uuid.uuid4().hex[:6]}", "storage_quota_mb": 5
    }, headers=headers).json()["id"]
    base = f"/api/workspaces/{ws_id}/files"

    def mkdir(name, parent=None):
        res = client.post(f"{base}/folders", json={"name": name, "parent_id": parent}, headers=headers)
        assert res.status_code == 201, res.text
        return res.json()["id"]

    def upload(name, content, folder=None):
        data = {"folder_id": str(folder)} if folder is not None else {}
        res = client.post(base, files={"file": (name, content, "text/plain")}, data=data, headers=headers)
        assert res.status_code == 201, res.text
        return res.json()["id"]

    docs = mkdir("Документы")
    reports = mkdir("Отчёты", docs)
    empty = mkdir("Пусто", docs)
    assert client.post(f"{base}/folders", json={"name": "документы"}, headers=headers).status_code == 409
    assert client.post(f"{base}/folders", json={"name": "../x"}, headers=headers).json()["id"]  # slashes neutralised

    root_file = upload("readme.txt", b"root")
    upload("plan.txt", b"plan-a", docs)
    upload("q1.txt", b"q1-report", reports)
    # Same name and size must not overwrite each other on disk
    dup1 = upload("same.txt", b"AAAA", reports)
    dup2 = upload("same.txt", b"BBBB", reports)

    listing = client.get(base, params={"folder_id": reports}, headers=headers).json()
    assert [b["name"] for b in listing["breadcrumbs"]] == ["Документы", "Отчёты"]
    assert sorted(f["file_name"] for f in listing["files"]) == ["q1.txt", "same.txt", "same.txt"]
    root = client.get(base, headers=headers).json()
    assert [f["file_name"] for f in root["files"]] == ["readme.txt"]
    docs_entry = next(f for f in root["folders"] if f["id"] == docs)
    assert docs_entry["size_bytes"] == len(b"plan-a") + len(b"q1-report") + 8

    paths = {f["path"] for f in client.get(f"{base}/folders", headers=headers).json()}
    assert "Документы/Отчёты" in paths

    # Archive: a folder keeps its structure, empty folders included, duplicates renamed
    res = client.post(f"{base}/archive", json={"folder_ids": [docs], "file_ids": [root_file]}, headers=headers)
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    names = set(zf.namelist())
    assert {"readme.txt", "Документы/plan.txt", "Документы/Отчёты/q1.txt", "Документы/Пусто/"} <= names
    same = sorted(n for n in names if "same" in n)
    assert same == ["Документы/Отчёты/same (2).txt", "Документы/Отчёты/same.txt"]
    assert {zf.read(n) for n in same} == {b"AAAA", b"BBBB"}

    single = client.post(f"{base}/archive", json={"folder_ids": [reports]}, headers=headers)
    assert "filename*=utf-8''%D0%9E%D1%82%D1%87%D1%91%D1%82%D1%8B.zip" in single.headers["content-disposition"]
    assert "Отчёты/q1.txt" in zipfile.ZipFile(io.BytesIO(single.content)).namelist()

    # Move: a folder cannot go inside itself; files and folders move to the root
    bad = client.post(f"{base}/move", json={"folder_ids": [docs], "target_folder_id": reports}, headers=headers)
    assert bad.status_code == 400
    assert client.post(f"{base}/move", json={"folder_ids": [empty], "file_ids": [dup1]}, headers=headers).status_code == 200
    root = client.get(base, headers=headers).json()
    assert {f["name"] for f in root["folders"]} >= {"Документы", "Пусто"}
    assert {f["id"] for f in root["files"]} == {root_file, dup1}

    # Recursive delete frees the storage of everything inside
    used_before = root["used_storage_bytes"]
    res = client.delete(f"{base}/folders/{docs}", headers=headers)
    assert res.json()["deleted_files"] == 3
    assert res.json()["used_storage_bytes"] == used_before - len(b"plan-a") - len(b"q1-report") - 4
    assert client.get(base, params={"folder_id": reports}, headers=headers).status_code == 404
    assert client.get(f"{base}/{dup2}/download", headers=headers).status_code == 404

def test_12_migration_adds_folder_column(tmp_path):
    """A database created before folders existed gets the new column on startup."""
    import asyncio
    import sqlite3
    from sqlalchemy.ext.asyncio import create_async_engine
    from backend.app import database

    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE workspacefile (id INTEGER PRIMARY KEY, workspace_id INTEGER, file_name TEXT, "
                "file_size_bytes INTEGER, mime_type TEXT, file_path TEXT, uploader_id INTEGER, created_at TEXT)")
    con.execute("INSERT INTO workspacefile VALUES (1, 1, 'old.txt', 3, 'text/plain', '/x', 1, '2026-01-01')")
    con.commit()
    con.close()

    async def migrate():
        engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
        async with engine.begin() as conn:
            await database._add_missing_columns(conn)
            await database._add_missing_columns(conn)  # idempotent
        await engine.dispose()

    asyncio.run(migrate())
    con = sqlite3.connect(db)
    cols = [r[1] for r in con.execute("PRAGMA table_info(workspacefile)")]
    assert "folder_id" in cols
    assert con.execute("SELECT file_name, folder_id FROM workspacefile").fetchone() == ("old.txt", None)

def test_13_download_security_headers():
    """Downloads are forced to attachment and sandboxed so an uploaded HTML/SVG cannot render on our origin."""
    headers = admin_headers()
    ws_id = client.post("/api/workspaces", json={
        "name": f"Download WS {uuid.uuid4().hex[:6]}", "storage_quota_mb": 5
    }, headers=headers).json()["id"]
    base = f"/api/workspaces/{ws_id}/files"

    upload = client.post(
        base,
        files={"file": ("evil.html", b"<script>alert(1)</script>", "text/html")},
        headers=headers
    )
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["id"]

    res = client.get(f"{base}/{file_id}/download", headers=headers)
    assert res.status_code == 200
    assert res.headers["content-disposition"].startswith("attachment")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["content-security-policy"] == "sandbox"

def test_14_ensure_secrets_replaces_placeholders(tmp_path):
    """Placeholder secrets are replaced by generated ones, persisted with 0600, and reused on restart."""
    upload_dir = str(tmp_path / "uploads")
    s = Settings(SECRET_KEY="", FINGERPRINT_PEPPER="eink_device_entropy_pepper_secure", UPLOAD_DIR=upload_dir)
    ensure_secrets(s)

    assert s.SECRET_KEY not in INSECURE_SECRETS and len(s.SECRET_KEY) >= 32
    assert s.FINGERPRINT_PEPPER not in INSECURE_SECRETS and len(s.FINGERPRINT_PEPPER) >= 32

    secrets_file = tmp_path / "secrets.json"
    assert secrets_file.exists()
    assert stat.S_IMODE(os.stat(secrets_file).st_mode) == 0o600

    again = Settings(SECRET_KEY="", FINGERPRINT_PEPPER="eink_device_entropy_pepper_secure", UPLOAD_DIR=upload_dir)
    ensure_secrets(again)
    assert again.SECRET_KEY == s.SECRET_KEY
    assert again.FINGERPRINT_PEPPER == s.FINGERPRINT_PEPPER

    explicit = Settings(SECRET_KEY="explicit-strong-key-0123456789abcdef", FINGERPRINT_PEPPER="", UPLOAD_DIR=str(tmp_path / "other"))
    ensure_secrets(explicit)
    assert explicit.SECRET_KEY == "explicit-strong-key-0123456789abcdef"

def test_15_no_wildcard_cors():
    """CORS is off by default, so a foreign Origin gets no Access-Control-Allow-Origin header."""
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers

def test_16_typst_requires_auth():
    """The Typst compile endpoint rejects anonymous requests."""
    # A fresh client: the shared one carries a session cookie, which trips the CSRF check (403) instead.
    anonymous = TestClient(app)
    res = anonymous.post("/api/typst/compile", json={"code": "= Hello", "format": "svg"})
    assert res.status_code == 401

def test_17_typst_timeout(monkeypatch):
    """A document that runs past TYPST_TIMEOUT_SECONDS is killed and reported as 408."""
    monkeypatch.setattr(settings, "TYPST_TIMEOUT_SECONDS", 1)
    # Typst memoizes recursive calls (fib-style recursion finishes fast). A bare long loop hits the
    # worker's 2 GB memory cap instead of running long, so the body does real math per iteration:
    # 8M iterations take ~3.8s here, well past the 1s limit, and stay under the cap.
    code = "#let s = 0\n#for i in range(8000000) { s = calc.sqrt(i) + calc.sin(i) }\n#s"
    res = client.post("/api/typst/compile", json={"code": code, "format": "svg"}, headers=admin_headers())
    assert res.status_code == 408
    assert res.json()["detail"] == "typst.timeout"

def test_18_typst_cannot_read_outside_root(tmp_path):
    """Typst's root is a private temp directory, so reading an arbitrary absolute path fails."""
    secret = tmp_path / "outside.txt"
    secret.write_text("not for typst", encoding="utf-8")
    code = f'#read("{secret}")'
    res = client.post("/api/typst/compile", json={"code": code, "format": "svg"}, headers=admin_headers())
    assert res.status_code == 400
    assert "not for typst" not in res.text

if __name__ == "__main__":
    pytest_exit = pytest.main(["-v", "-s", __file__])
    sys.exit(pytest_exit)
