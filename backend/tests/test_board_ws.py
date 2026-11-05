import json
import os
import sys
import time
import uuid

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.app.main import app
from backend.app.config import settings
from backend.app.routes.board_ws import apply_ops, parse_board, validate_batch

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404


# ---------- helpers ----------

@pytest.fixture(scope="module")
def http():
    with TestClient(app) as c:
        yield c


def _login(http) -> str:
    res = http.post("/api/auth/login", json={
        "username": settings.SUPERADMIN_USERNAME,
        "password": settings.SUPERADMIN_PASSWORD,
    })
    assert res.status_code == 200
    return res.json()["access_token"]


@pytest.fixture(scope="module")
def token(http):
    return _login(http)


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _cookie(token: str) -> dict:
    return {"cookie": f"piop_session={token}"}


def _make_board(http, token, doc_type="canvas", content=""):
    headers = _bearer(token)
    ws = http.post("/api/workspaces", json={
        "name": f"Board WS {uuid.uuid4().hex[:6]}",
        "description": "board ws test",
        "storage_quota_mb": 10,
    }, headers=headers)
    assert ws.status_code == 201
    wid = ws.json()["id"]
    doc = http.post(f"/api/workspaces/{wid}/documents", json={
        "title": "Board", "doc_type": doc_type, "content_raw": content,
    }, headers=headers)
    assert doc.status_code == 201
    return wid, doc.json()["id"]


def _path(wid, did) -> str:
    return f"/api/workspaces/{wid}/documents/{did}/ws"


def _recv_until(ws, kind: str) -> dict:
    while True:
        msg = json.loads(ws.receive_text())
        if msg["t"] == kind:
            return msg


def _send_ops(ws, cid: int, ops: list):
    ws.send_text(json.dumps({"t": "ops", "cid": cid, "ops": ops}))


def _stored_element_ids(http, token, wid, did):
    doc = http.get(f"/api/workspaces/{wid}/documents/{did}", headers=_bearer(token)).json()
    try:
        board = json.loads(doc["content_raw"])
    except ValueError:
        return []
    return [e["id"] for layer in board.get("layers", []) for e in layer.get("elements", [])]


def _wait_until(pred, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


# ---------- socket behaviour ----------

def test_two_clients_share_ops_and_disconnect_flushes(http, token):
    wid, did = _make_board(http, token)
    path = _path(wid, did)
    with http.websocket_connect(path, headers=_cookie(token)) as a:
        init_a = _recv_until(a, "init")
        with http.websocket_connect(path, headers=_cookie(token)) as b:
            init_b = _recv_until(b, "init")
            assert len(init_b["peers"]) == 2
            _recv_until(a, "peers")

            layer_id = init_b["doc"]["layers"][0]["id"]
            op = {"op": "el.add", "layer": layer_id, "index": 0, "el": {"id": "e1", "type": "rect", "x": 1}}
            _send_ops(a, 1, [op])

            ack = _recv_until(a, "ack")
            assert ack["cid"] == 1
            assert ack["seq"] == init_b["seq"] + 1

            relayed = _recv_until(b, "ops")
            assert relayed["ops"] == [op]
            assert relayed["seq"] == ack["seq"]
            assert relayed["from"] == init_a["you"]

    # Both clients are gone: the last disconnect must write the board (debounce alone would take 2 s).
    assert _wait_until(lambda: "e1" in _stored_element_ids(http, token, wid, did), timeout=1.5)


def test_invalid_batch_is_not_applied_and_client_gets_init(http, token):
    wid, did = _make_board(http, token)
    with http.websocket_connect(_path(wid, did), headers=_cookie(token)) as a:
        init = _recv_until(a, "init")
        layer_id = init["doc"]["layers"][0]["id"]
        good = {"op": "el.add", "layer": layer_id, "index": 0, "el": {"id": "e9", "type": "rect"}}
        bad = {"op": "el.set", "id": "e9", "set": {"id": "other"}}
        _send_ops(a, 2, [good, bad])

        resync = _recv_until(a, "init")
        assert resync["doc"] == init["doc"]
        assert resync["seq"] == init["seq"]

        # Nothing from the rejected batch was acked: the next message back is the pong.
        a.send_text(json.dumps({"t": "ping"}))
        assert json.loads(a.receive_text())["t"] == "pong"


def test_reset_is_pushed_after_http_put(http, token):
    wid, did = _make_board(http, token)
    with http.websocket_connect(_path(wid, did), headers=_cookie(token)) as ws:
        _recv_until(ws, "init")
        new_board = {
            "version": 2,
            "layers": [{"id": "lx", "name": "X", "visible": True, "locked": False, "elements": []}],
            "activeLayerId": "lx",
            "background": "grid",
            "view": {"x": 0, "y": 0, "zoom": 1},
        }
        res = http.put(f"/api/workspaces/{wid}/documents/{did}",
                       json={"content_raw": json.dumps(new_board)}, headers=_bearer(token))
        assert res.status_code == 200
        reset = _recv_until(ws, "reset")
        assert reset["doc"]["layers"][0]["id"] == "lx"
        assert reset["doc"]["background"] == "grid"


# ---------- handshake ----------

def test_no_cookie_closes_4401(http, token):
    wid, did = _make_board(http, token)
    fresh = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with fresh.websocket_connect(_path(wid, did)) as ws:
            ws.receive_text()
    assert exc.value.code == CLOSE_UNAUTHORIZED


def test_foreign_origin_closes_4403(http, token):
    wid, did = _make_board(http, token)
    with pytest.raises(WebSocketDisconnect) as exc:
        with http.websocket_connect(_path(wid, did), headers={**_cookie(token), "origin": "http://evil.example"}) as ws:
            ws.receive_text()
    assert exc.value.code == CLOSE_FORBIDDEN


def test_same_host_origin_is_accepted(http, token):
    wid, did = _make_board(http, token)
    with http.websocket_connect(_path(wid, did), headers={**_cookie(token), "origin": "http://testserver"}) as ws:
        assert _recv_until(ws, "init")["t"] == "init"


def test_non_canvas_document_closes_4404(http, token):
    wid, did = _make_board(http, token, doc_type="doc", content="plain text")
    with pytest.raises(WebSocketDisconnect) as exc:
        with http.websocket_connect(_path(wid, did), headers=_cookie(token)) as ws:
            ws.receive_text()
    assert exc.value.code == CLOSE_NOT_FOUND


# ---------- op semantics (no socket) ----------

def _board():
    return {
        "version": 2,
        "layers": [
            {"id": "L1", "name": "A", "visible": True, "locked": False,
             "elements": [{"id": "a", "type": "r"}, {"id": "b", "type": "r"}, {"id": "c", "type": "r"}]},
            {"id": "L2", "name": "B", "visible": True, "locked": False,
             "elements": [{"id": "d", "type": "r"}]},
        ],
        "activeLayerId": "L1",
        "background": "dots",
        "view": {"x": 0, "y": 0, "zoom": 1},
    }


def _layer(doc, layer_id):
    return next(layer for layer in doc["layers"] if layer["id"] == layer_id)


def _ids(doc, layer_id):
    return [e["id"] for e in _layer(doc, layer_id)["elements"]]


def test_el_add_moves_element_and_clamps_index():
    doc = _board()
    apply_ops(doc, [{"op": "el.add", "layer": "L2", "index": 99, "el": {"id": "a", "type": "x"}}])
    assert _ids(doc, "L1") == ["b", "c"]
    assert _ids(doc, "L2") == ["d", "a"]
    assert _layer(doc, "L2")["elements"][1]["type"] == "x"


def test_el_add_to_missing_layer_is_skipped():
    doc = _board()
    before = json.dumps(doc, sort_keys=True)
    apply_ops(doc, [{"op": "el.add", "layer": "NOPE", "index": 0, "el": {"id": "a", "type": "x"}}])
    assert json.dumps(doc, sort_keys=True) == before


def test_el_set_merges_and_unsets():
    doc = _board()
    apply_ops(doc, [{"op": "el.set", "id": "a", "set": {"x": 5}, "unset": ["type"]}])
    assert _layer(doc, "L1")["elements"][0] == {"id": "a", "x": 5}


def test_el_set_on_missing_element_is_skipped():
    doc = _board()
    before = json.dumps(doc, sort_keys=True)
    apply_ops(doc, [{"op": "el.set", "id": "zz", "set": {"x": 5}}])
    assert json.dumps(doc, sort_keys=True) == before


def test_el_del_removes_and_missing_is_skipped():
    doc = _board()
    apply_ops(doc, [{"op": "el.del", "id": "b"}, {"op": "el.del", "id": "zz"}])
    assert _ids(doc, "L1") == ["a", "c"]


def test_el_order_lists_first_then_unlisted_in_current_order():
    doc = _board()
    apply_ops(doc, [{"op": "el.order", "layer": "L1", "ids": ["c", "zz", "a"]}])
    assert _ids(doc, "L1") == ["c", "a", "b"]


def test_layer_add_takes_elements_from_other_layers():
    doc = _board()
    apply_ops(doc, [{"op": "layer.add", "index": 0, "layer": {
        "id": "L3", "name": "C", "visible": True, "locked": False, "elements": [{"id": "a", "type": "r"}],
    }}])
    assert [layer["id"] for layer in doc["layers"]] == ["L3", "L1", "L2"]
    assert _ids(doc, "L3") == ["a"]
    assert _ids(doc, "L1") == ["b", "c"]


def test_layer_set_assigns_allowed_keys():
    doc = _board()
    apply_ops(doc, [{"op": "layer.set", "id": "L1", "set": {"name": "Z", "visible": False, "locked": True}}])
    layer = _layer(doc, "L1")
    assert (layer["name"], layer["visible"], layer["locked"]) == ("Z", False, True)


def test_layer_del_removes_but_never_the_only_layer():
    doc = _board()
    apply_ops(doc, [{"op": "layer.del", "id": "L2"}])
    assert [layer["id"] for layer in doc["layers"]] == ["L1"]
    apply_ops(doc, [{"op": "layer.del", "id": "L1"}])
    assert [layer["id"] for layer in doc["layers"]] == ["L1"]


def test_layer_order_lists_first_then_unlisted():
    doc = _board()
    apply_ops(doc, [{"op": "layer.order", "ids": ["L2", "missing"]}])
    assert [layer["id"] for layer in doc["layers"]] == ["L2", "L1"]


def test_doc_set_background():
    doc = _board()
    apply_ops(doc, [{"op": "doc.set", "set": {"background": "grid"}}])
    assert doc["background"] == "grid"


def test_title_op_is_returned_not_stored_in_board():
    doc = _board()
    assert apply_ops(doc, [{"op": "title", "title": "Renamed"}]) == "Renamed"
    assert apply_ops(doc, [{"op": "doc.set", "set": {"background": "none"}}]) is None
    assert "title" not in doc


@pytest.mark.parametrize("ops", [
    [{"op": "el.set", "id": "a", "set": {"id": "x"}}],
    [{"op": "el.set", "id": "a", "set": {}, "unset": ["id"]}],
    [{"op": "el.add", "layer": "L1", "index": True, "el": {"id": "a"}}],
    [{"op": "el.add", "layer": "L1", "index": 0, "el": {}}],
    [{"op": "layer.set", "id": "L1", "set": {"id": "other"}}],
    [{"op": "layer.set", "id": "L1", "set": {"name": "x" * 61}}],
    [{"op": "layer.set", "id": "L1", "set": {"visible": "yes"}}],
    [{"op": "doc.set", "set": {"background": "x" * 21}}],
    [{"op": "title", "title": ""}],
    [{"op": "nope"}],
    [{"op": "el.del", "id": ""}],
    [{"op": "el.del", "id": "a"}, "not an object"],
    [{"op": "el.del", "id": "a"}] * 5001,
])
def test_validate_rejects_malformed_batches(ops):
    with pytest.raises(ValueError):
        validate_batch(ops)


def test_validate_accepts_well_formed_batch():
    validate_batch([
        {"op": "el.add", "layer": "L1", "index": 0, "el": {"id": "a"}},
        {"op": "el.set", "id": "a", "set": {"x": 1}, "unset": ["y"]},
        {"op": "title", "title": "T"},
    ])


def test_parse_board_wraps_plain_content_and_keeps_v2():
    fresh = parse_board("")
    assert fresh["version"] == 2 and len(fresh["layers"]) == 1
    assert fresh["activeLayerId"] == fresh["layers"][0]["id"]

    image = parse_board("data:image/png;base64,AAAA")
    assert image["layers"][0]["elements"][0]["type"] == "image"
    assert image["layers"][0]["elements"][0]["src"] == "data:image/png;base64,AAAA"

    kept = _board()
    assert parse_board(json.dumps(kept)) == kept
