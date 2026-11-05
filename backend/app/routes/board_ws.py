"""Realtime collaboration for whiteboard boards (canvas documents) over a WebSocket.

One in-memory room per board exists while at least one client is connected. The server applies every
accepted batch under the room lock, so `seq` is a total order, then acks the sender and broadcasts to the
rest. Changes are persisted debounced into Document.content_raw and flushed when the last client leaves.
Protocol: docs in the whiteboard spec (protocol.md).
"""
import asyncio
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlsplit

import anyio
from fastapi import APIRouter, HTTPException, WebSocket

from backend.app.auth import SESSION_COOKIE, user_from_session_token
from backend.app.database import async_session_factory
from backend.app.models import Document

logger = logging.getLogger(__name__)

router = APIRouter()

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404

SAVE_DELAY = 2.0       # seconds of quiet before a debounced save
SAVE_MAX_DELAY = 10.0  # an unsaved change is never older than this
MAX_OPS = 5000
ACCESS_RECHECK_SECONDS = 30.0  # an open socket re-checks its user's access at most this often


# ---------- document model ----------

def _new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(6)


def parse_board(content_raw: str) -> dict:
    """Stored content -> board dict. Anything that is not a v2 board becomes a fresh one."""
    try:
        data = json.loads(content_raw)
    except (TypeError, ValueError):
        data = None
    if isinstance(data, dict) and data.get("version") == 2 and isinstance(data.get("layers"), list) and data["layers"]:
        return data
    layer_id = _new_id("l")
    elements = []
    if content_raw.startswith("data:image"):
        elements.append({"id": _new_id("e"), "type": "image", "x": 0, "y": 0, "w": 0, "h": 0,
                         "src": content_raw, "autoSize": True})
    return {
        "version": 2,
        "layers": [{"id": layer_id, "name": "Layer 1", "visible": True, "locked": False, "elements": elements}],
        "activeLayerId": layer_id,
        "background": "dots",
        "view": {"x": 0, "y": 0, "zoom": 1},
    }


def _public(doc: dict) -> dict:
    return {"layers": doc["layers"], "background": doc.get("background", "dots")}


# ---------- op validation ----------

def _is_id(v) -> bool:
    return isinstance(v, str) and 1 <= len(v) <= 64


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_ids(v) -> bool:
    return isinstance(v, list) and all(_is_id(i) for i in v)


def _keys_within(d, allowed: set) -> bool:
    return isinstance(d, dict) and set(d) <= allowed


def _v_el_add(op) -> bool:
    return (_is_id(op.get("layer")) and _is_int(op.get("index"))
            and isinstance(op.get("el"), dict) and _is_id(op["el"].get("id")))


def _v_el_set(op) -> bool:
    if not _is_id(op.get("id")) or not isinstance(op.get("set"), dict) or "id" in op["set"]:
        return False
    unset = op.get("unset", [])
    return isinstance(unset, list) and all(isinstance(k, str) and k != "id" for k in unset)


def _v_el_del(op) -> bool:
    return _is_id(op.get("id"))


def _v_el_order(op) -> bool:
    return _is_id(op.get("layer")) and _is_ids(op.get("ids"))


def _v_layer_add(op) -> bool:
    layer = op.get("layer")
    if not _is_int(op.get("index")) or not isinstance(layer, dict) or not _is_id(layer.get("id")):
        return False
    elements = layer.get("elements", [])
    return isinstance(elements, list) and all(isinstance(e, dict) and _is_id(e.get("id")) for e in elements)


def _v_layer_set(op) -> bool:
    if not _is_id(op.get("id")) or not _keys_within(op.get("set"), {"name", "visible", "locked"}):
        return False
    s = op["set"]
    if "name" in s and not (isinstance(s["name"], str) and len(s["name"]) <= 60):
        return False
    return all(isinstance(s[k], bool) for k in ("visible", "locked") if k in s)


def _v_layer_del(op) -> bool:
    return _is_id(op.get("id"))


def _v_layer_order(op) -> bool:
    return _is_ids(op.get("ids"))


def _v_doc_set(op) -> bool:
    if not _keys_within(op.get("set"), {"background"}):
        return False
    bg = op["set"].get("background", "")
    return isinstance(bg, str) and len(bg) <= 20


def _v_title(op) -> bool:
    return isinstance(op.get("title"), str) and 1 <= len(op["title"]) <= 200


_VALIDATORS = {
    "el.add": _v_el_add,
    "el.set": _v_el_set,
    "el.del": _v_el_del,
    "el.order": _v_el_order,
    "layer.add": _v_layer_add,
    "layer.set": _v_layer_set,
    "layer.del": _v_layer_del,
    "layer.order": _v_layer_order,
    "doc.set": _v_doc_set,
    "title": _v_title,
}


def validate_batch(ops) -> None:
    """Raises ValueError if the batch is malformed. Nothing is applied before this passes."""
    if not isinstance(ops, list) or len(ops) > MAX_OPS:
        raise ValueError("batch")
    for op in ops:
        if not isinstance(op, dict):
            raise ValueError("op")
        validator = _VALIDATORS.get(op.get("op"))
        if validator is None or not validator(op):
            raise ValueError(f"invalid op {op.get('op')!r}")


# ---------- op application ----------

def _layer(doc: dict, layer_id: str) -> Optional[dict]:
    for layer in doc["layers"]:
        if layer.get("id") == layer_id:
            return layer
    return None


def _locate(doc: dict, element_id: str):
    for layer in doc["layers"]:
        for i, el in enumerate(layer.get("elements", [])):
            if el.get("id") == element_id:
                return layer, i
    return None


def _remove_element(doc: dict, element_id: str) -> None:
    found = _locate(doc, element_id)
    if found:
        layer, i = found
        del layer["elements"][i]


def _reorder(items: list, ids: list) -> list:
    by_id = {}
    for item in items:
        by_id.setdefault(item.get("id"), item)
    listed, seen = [], set()
    for wanted in ids:
        if wanted in by_id and wanted not in seen:
            listed.append(by_id[wanted])
            seen.add(wanted)
    return listed + [item for item in items if item.get("id") not in seen]


def _clamp(index: int, length: int) -> int:
    return max(0, min(index, length))


def _op_el_add(doc: dict, op: dict) -> None:
    layer = _layer(doc, op["layer"])
    if layer is None:
        return
    _remove_element(doc, op["el"]["id"])
    elements = layer.setdefault("elements", [])
    elements.insert(_clamp(op["index"], len(elements)), op["el"])


def _op_el_set(doc: dict, op: dict) -> None:
    found = _locate(doc, op["id"])
    if found is None:
        return
    layer, i = found
    new = dict(layer["elements"][i])
    new.update(op.get("set", {}))
    for key in op.get("unset", []):
        new.pop(key, None)
    layer["elements"][i] = new


def _op_el_del(doc: dict, op: dict) -> None:
    _remove_element(doc, op["id"])


def _op_el_order(doc: dict, op: dict) -> None:
    layer = _layer(doc, op["layer"])
    if layer is None:
        return
    layer["elements"] = _reorder(layer.get("elements", []), op["ids"])


def _op_layer_add(doc: dict, op: dict) -> None:
    new = op["layer"]
    new.setdefault("elements", [])
    doc["layers"] = [layer for layer in doc["layers"] if layer.get("id") != new["id"]]
    for el in new["elements"]:
        _remove_element(doc, el["id"])
    layers = doc["layers"]
    layers.insert(_clamp(op["index"], len(layers)), new)


def _op_layer_set(doc: dict, op: dict) -> None:
    layer = _layer(doc, op["id"])
    if layer is not None:
        layer.update(op["set"])


def _op_layer_del(doc: dict, op: dict) -> None:
    layer = _layer(doc, op["id"])
    if layer is None or len(doc["layers"]) <= 1:
        return
    doc["layers"] = [other for other in doc["layers"] if other is not layer]


def _op_layer_order(doc: dict, op: dict) -> None:
    doc["layers"] = _reorder(doc["layers"], op["ids"])


def _op_doc_set(doc: dict, op: dict) -> None:
    doc.update(op["set"])


_APPLIERS = {
    "el.add": _op_el_add,
    "el.set": _op_el_set,
    "el.del": _op_el_del,
    "el.order": _op_el_order,
    "layer.add": _op_layer_add,
    "layer.set": _op_layer_set,
    "layer.del": _op_layer_del,
    "layer.order": _op_layer_order,
    "doc.set": _op_doc_set,
}


def apply_ops(doc: dict, ops: list) -> Optional[str]:
    """Applies already-validated ops to the board dict in place. Returns the title if a title op ran."""
    new_title = None
    for op in ops:
        if op["op"] == "title":
            new_title = op["title"]
        else:
            _APPLIERS[op["op"]](doc, op)
    return new_title


# ---------- persistence ----------

async def _load_document(document_id: int) -> Optional[tuple[str, str]]:
    async with async_session_factory() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return None
        return doc.content_raw, doc.title


async def _save_document(document_id: int, content: str, title: str) -> bool:
    async with async_session_factory() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return False
        doc.content_raw = content
        doc.title = title
        doc.updated_at = datetime.now(timezone.utc)
        session.add(doc)
        await session.commit()
        return True


# ---------- rooms ----------

def _dumps(msg: dict) -> str:
    return json.dumps(msg, ensure_ascii=False)


class Room:
    def __init__(self, document_id: int, doc: dict, title: str):
        self.document_id = document_id
        self.doc = doc
        self.title = title
        self.seq = 0
        self.clients: dict[str, tuple[WebSocket, str]] = {}  # conn_id -> (socket, username)
        self.lock = asyncio.Lock()
        self.save_task: Optional[asyncio.Task] = None
        self.dirty = False
        self.first_dirty = 0.0
        self.last_change = 0.0
        self.closed = False


def _peers(room: Room) -> list:
    return [{"id": conn_id, "user": user} for conn_id, (_, user) in room.clients.items()]


def _init_msg(room: Room, conn_id: str) -> dict:
    return {"t": "init", "doc": _public(room.doc), "title": room.title, "seq": room.seq,
            "you": conn_id, "peers": _peers(room)}


class RoomManager:
    def __init__(self):
        self.rooms: dict[int, Room] = {}

    async def join(self, document_id: int, conn_id: str, ws: WebSocket, username: str) -> Optional[Room]:
        while True:
            room = self.rooms.get(document_id)
            if room is None:
                loaded = await _load_document(document_id)
                if loaded is None:
                    return None
                # Another client may have created the room while we were loading.
                room = self.rooms.get(document_id)
                if room is None:
                    room = Room(document_id, parse_board(loaded[0]), loaded[1])
                    self.rooms[document_id] = room
            async with room.lock:
                if room.closed:
                    continue  # closed while we waited: reload from the database
                room.clients[conn_id] = (ws, username)
                await self._send(room, conn_id, _init_msg(room, conn_id))
                await self._broadcast_peers(room)
                return room

    async def leave(self, room: Room, conn_id: str) -> None:
        async with room.lock:
            if room.closed:
                return
            room.clients.pop(conn_id, None)
            if not room.clients:
                await self._close_room(room, code=None)
            else:
                await self._broadcast_peers(room)

    async def resync(self, room: Room, conn_id: str) -> None:
        async with room.lock:
            if not room.closed:
                await self._send(room, conn_id, _init_msg(room, conn_id))

    async def handle_message(self, room: Room, conn_id: str, text: str) -> None:
        try:
            msg = json.loads(text)
        except ValueError:
            msg = None
        if isinstance(msg, dict) and msg.get("t") == "ping":
            async with room.lock:
                if not room.closed:
                    await self._send(room, conn_id, {"t": "pong"})
            return
        if (isinstance(msg, dict) and msg.get("t") == "ops"
                and _is_int(msg.get("cid")) and isinstance(msg.get("ops"), list)):
            await self._apply_batch(room, conn_id, msg["cid"], msg["ops"])
            return
        await self.resync(room, conn_id)

    async def external_update(self, document_id: int, content_raw: str, title: str) -> None:
        """Called after an HTTP/AI write replaced the stored board: reload the room and tell everyone."""
        room = self.rooms.get(document_id)
        if room is None:
            return
        async with room.lock:
            if room.closed:
                return
            self._cancel_save(room)
            room.doc = parse_board(content_raw)
            room.title = title
            room.dirty = False
            room.seq += 1
            await self._broadcast(room, {"t": "reset", "doc": _public(room.doc), "title": room.title, "seq": room.seq})

    async def close_document(self, document_id: int) -> None:
        """Called after the document was deleted: drop the room and close its sockets."""
        room = self.rooms.get(document_id)
        if room is None:
            return
        async with room.lock:
            if not room.closed:
                await self._close_room(room, code=CLOSE_NOT_FOUND)

    # -- internals (all called with room.lock held, except the public entry points above) --

    async def _apply_batch(self, room: Room, conn_id: str, cid: int, ops: list) -> None:
        async with room.lock:
            if room.closed or conn_id not in room.clients:
                return
            try:
                validate_batch(ops)
            except ValueError:
                await self._send(room, conn_id, _init_msg(room, conn_id))
                return
            new_title = apply_ops(room.doc, ops)
            if new_title is not None:
                room.title = new_title
            room.seq += 1
            seq = room.seq
            self._mark_dirty(room)
            await self._send(room, conn_id, {"t": "ack", "cid": cid, "seq": seq})
            await self._broadcast(room, {"t": "ops", "ops": ops, "seq": seq, "from": conn_id}, exclude=conn_id)

    async def _send(self, room: Room, conn_id: str, msg: dict) -> bool:
        entry = room.clients.get(conn_id)
        if entry is None:
            return False
        try:
            await entry[0].send_text(_dumps(msg))
            return True
        except Exception:
            room.clients.pop(conn_id, None)
            if room.clients:
                await self._broadcast_peers(room)
            return False

    async def _broadcast(self, room: Room, msg: dict, exclude: Optional[str] = None) -> None:
        text = _dumps(msg)
        failed = False
        for conn_id, (ws, _) in list(room.clients.items()):
            if conn_id == exclude:
                continue
            try:
                await ws.send_text(text)
            except Exception:
                room.clients.pop(conn_id, None)
                failed = True
        if failed and room.clients:
            await self._broadcast_peers(room)

    async def _broadcast_peers(self, room: Room) -> None:
        await self._broadcast(room, {"t": "peers", "peers": _peers(room)})

    def _mark_dirty(self, room: Room) -> None:
        now = asyncio.get_running_loop().time()
        if not room.dirty:
            room.dirty = True
            room.first_dirty = now
        room.last_change = now
        if room.save_task is None:
            room.save_task = asyncio.create_task(self._save_loop(room))

    def _cancel_save(self, room: Room) -> None:
        if room.save_task is not None and room.save_task is not asyncio.current_task():
            room.save_task.cancel()
        room.save_task = None

    async def _save_loop(self, room: Room) -> None:
        loop = asyncio.get_running_loop()
        while True:
            async with room.lock:
                if room.closed or not room.dirty:
                    room.save_task = None
                    return
                delay = min(room.last_change + SAVE_DELAY, room.first_dirty + SAVE_MAX_DELAY) - loop.time()
                if delay <= 0:
                    if not await self._write(room):
                        await self._close_room(room, code=CLOSE_NOT_FOUND)
                        return
                    continue
            await asyncio.sleep(delay)

    async def _write(self, room: Room) -> bool:
        """Persists the board. False if the document no longer exists."""
        content = json.dumps(room.doc, ensure_ascii=False, separators=(",", ":"))
        now = asyncio.get_running_loop().time()
        room.dirty = False
        try:
            return await _save_document(room.document_id, content, room.title)
        except Exception:
            logger.exception("saving board %s failed, will retry", room.document_id)
            room.dirty = True
            room.first_dirty = room.last_change = now
            return True

    async def _close_room(self, room: Room, code: Optional[int]) -> None:
        self._cancel_save(room)
        if code is None:
            if room.dirty:
                await self._write(room)
        else:
            for ws, _ in list(room.clients.values()):
                try:
                    await ws.close(code=code)
                except Exception:
                    pass
        room.clients.clear()
        room.closed = True
        if self.rooms.get(room.document_id) is room:
            del self.rooms[room.document_id]


board_rooms = RoomManager()


# ---------- endpoint ----------

async def _check_access(token: Optional[str], workspace_id: int, document_id: int) -> tuple[Optional[str], Optional[int]]:
    """Session, membership and document checks. Returns (username, None) or (None, close_code)."""
    if not token:
        return None, CLOSE_UNAUTHORIZED

    # Imported here: documents.py imports this module to fire the room hooks.
    from backend.app.routes.documents import verify_member

    async with async_session_factory() as session:
        user = await user_from_session_token(token, session)
        if user is None:
            return None, CLOSE_UNAUTHORIZED
        try:
            await verify_member(workspace_id, user, session)
        except HTTPException:
            return None, CLOSE_FORBIDDEN
        doc = await session.get(Document, document_id)
        if doc is None or doc.workspace_id != workspace_id or doc.doc_type != "canvas":
            return None, CLOSE_NOT_FOUND
        return user.username, None


async def _authorize(websocket: WebSocket, workspace_id: int, document_id: int) -> tuple[Optional[str], Optional[int]]:
    """Handshake checks in protocol order. Returns (username, None) or (None, close_code)."""
    origin = websocket.headers.get("origin")
    if origin is not None:
        origin_host = urlsplit(origin).hostname
        host_name = urlsplit("//" + websocket.headers.get("host", "")).hostname
        if not origin_host or origin_host != host_name:
            return None, CLOSE_FORBIDDEN

    return await _check_access(websocket.cookies.get(SESSION_COOKIE), workspace_id, document_id)


@router.websocket("/api/workspaces/{workspace_id}/documents/{document_id}/ws")
async def board_socket(websocket: WebSocket, workspace_id: int, document_id: int):
    await websocket.accept()
    username, code = await _authorize(websocket, workspace_id, document_id)
    if code is not None:
        await websocket.close(code=code)
        return
    token = websocket.cookies.get(SESSION_COOKIE)

    conn_id = uuid.uuid4().hex[:12]
    room = await board_rooms.join(document_id, conn_id, websocket, username)
    if room is None:
        await websocket.close(code=CLOSE_NOT_FOUND)
        return
    loop = asyncio.get_running_loop()
    checked_at = loop.time()
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            # Access is re-checked on incoming traffic, at most once per ACCESS_RECHECK_SECONDS.
            if loop.time() - checked_at >= ACCESS_RECHECK_SECONDS:
                checked_at = loop.time()
                _, code = await _check_access(token, workspace_id, document_id)
                if code is not None:
                    await websocket.close(code=code)
                    break
            text = message.get("text")
            if text is None:
                await board_rooms.resync(room, conn_id)
            else:
                await board_rooms.handle_message(room, conn_id, text)
    finally:
        # Shielded: the flush of the last client must finish even when this task is cancelled.
        with anyio.CancelScope(shield=True):
            await board_rooms.leave(room, conn_id)
