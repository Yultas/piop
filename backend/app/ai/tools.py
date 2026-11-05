"""
Workspace tools the assistant can call.

Every tool runs on behalf of the requesting user inside one workspace and
verifies that the objects it touches belong to that workspace. The tool kind
(read / write / delete) decides its default permission mode.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.app.models import Channel, Document, Message, Task, User, WorkspaceFile, WorkspaceFolder
from backend.app.search import search_workspace

DEFAULT_MODES = {"read": "auto", "write": "confirm", "delete": "off"}
MODES = ("off", "confirm", "auto")
MAX_DOCUMENT_CHARS = 20000
TASK_STATUSES = ["todo", "in_progress", "done"]
TASK_PRIORITIES = ["low", "medium", "high"]


class ToolError(Exception):
    """Expected failure reported back to the model as the tool result."""


@dataclass
class ToolContext:
    # Plain ids rather than ORM objects: they stay valid after a session rollback
    session: AsyncSession
    user_id: int
    workspace_id: int


@dataclass
class Tool:
    name: str
    kind: str
    description: str
    parameters: dict
    handler: Callable[[ToolContext, dict], Awaitable[Any]]

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


def _obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


async def _get_owned(ctx: ToolContext, model, obj_id: Any, label: str):
    try:
        obj = await ctx.session.get(model, int(obj_id))
    except (TypeError, ValueError):
        obj = None
    if not obj or getattr(obj, "workspace_id", None) != ctx.workspace_id:
        raise ToolError(f"{label} {obj_id} not found in this workspace")
    return obj


def _task_dict(t: Task) -> dict:
    return {
        "id": t.id, "title": t.title, "description": t.description, "status": t.status,
        "priority": t.priority, "due_date": t.due_date.isoformat() if t.due_date else None,
    }


# ---- read tools ----

async def _search(ctx: ToolContext, args: dict):
    hits = await search_workspace(
        ctx.session, ctx.workspace_id, str(args.get("query", "")),
        kinds=args.get("kinds"), limit=int(args.get("limit") or 10),
    )
    return {"results": hits, "count": len(hits)}


async def _list_tasks(ctx: ToolContext, args: dict):
    stmt = select(Task).where(Task.workspace_id == ctx.workspace_id).order_by(Task.created_at.desc())
    if args.get("status"):
        stmt = stmt.where(Task.status == args["status"])
    tasks = (await ctx.session.execute(stmt)).scalars().all()
    return {"tasks": [_task_dict(t) for t in tasks]}


async def _list_documents(ctx: ToolContext, args: dict):
    stmt = select(Document).where(Document.workspace_id == ctx.workspace_id).order_by(Document.updated_at.desc())
    if args.get("doc_type"):
        stmt = stmt.where(Document.doc_type == args["doc_type"])
    docs = (await ctx.session.execute(stmt)).scalars().all()
    return {"documents": [
        {"id": d.id, "title": d.title, "doc_type": d.doc_type, "updated_at": d.updated_at.isoformat(),
         "length": len(d.content_raw or "")}
        for d in docs
    ]}


async def _read_document(ctx: ToolContext, args: dict):
    doc = await _get_owned(ctx, Document, args.get("document_id"), "Document")
    content = doc.content_raw or ""
    return {
        "id": doc.id, "title": doc.title, "doc_type": doc.doc_type,
        "content": content[:MAX_DOCUMENT_CHARS], "truncated": len(content) > MAX_DOCUMENT_CHARS,
    }


async def _list_channels(ctx: ToolContext, args: dict):
    channels = (await ctx.session.execute(
        select(Channel).where(Channel.workspace_id == ctx.workspace_id)
    )).scalars().all()
    return {"channels": [{"id": c.id, "name": c.name} for c in channels]}


async def _read_messages(ctx: ToolContext, args: dict):
    channel = await _get_owned(ctx, Channel, args.get("channel_id"), "Channel")
    limit = max(1, min(int(args.get("limit") or 30), 100))
    rows = (await ctx.session.execute(
        select(Message, User.username)
        .join(User, User.id == Message.sender_id)
        .where(Message.channel_id == channel.id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )).all()
    return {"channel": channel.name, "messages": [
        {"id": m.id, "author": name, "content": m.content, "thread_parent_id": m.thread_parent_id,
         "created_at": m.created_at.isoformat()}
        for m, name in reversed(rows)
    ]}


async def _list_files(ctx: ToolContext, args: dict):
    folders = {
        f.id: f for f in (await ctx.session.execute(
            select(WorkspaceFolder).where(WorkspaceFolder.workspace_id == ctx.workspace_id)
        )).scalars().all()
    }

    def path(folder_id):
        parts = []
        while folder_id in folders:
            parts.append(folders[folder_id].name)
            folder_id = folders[folder_id].parent_id
        return "/" + "/".join(reversed(parts))

    files = (await ctx.session.execute(
        select(WorkspaceFile).where(WorkspaceFile.workspace_id == ctx.workspace_id)
    )).scalars().all()
    return {"files": [
        {"id": f.id, "name": f.file_name, "folder": path(f.folder_id), "size_bytes": f.file_size_bytes,
         "mime_type": f.mime_type}
        for f in files
    ]}


# ---- write tools ----

def _check_choice(value, allowed: list[str], field: str):
    if value is not None and value not in allowed:
        raise ToolError(f"{field} must be one of {allowed}")


async def _create_task(ctx: ToolContext, args: dict):
    title = str(args.get("title") or "").strip()
    if not title:
        raise ToolError("title is required")
    _check_choice(args.get("status"), TASK_STATUSES, "status")
    _check_choice(args.get("priority"), TASK_PRIORITIES, "priority")
    task = Task(
        workspace_id=ctx.workspace_id, title=title, description=args.get("description") or "",
        status=args.get("status") or "todo", priority=args.get("priority") or "medium",
    )
    ctx.session.add(task)
    await ctx.session.commit()
    await ctx.session.refresh(task)
    return {"created": _task_dict(task)}


async def _update_task(ctx: ToolContext, args: dict):
    task = await _get_owned(ctx, Task, args.get("task_id"), "Task")
    _check_choice(args.get("status"), TASK_STATUSES, "status")
    _check_choice(args.get("priority"), TASK_PRIORITIES, "priority")
    for field in ("title", "description", "status", "priority"):
        if args.get(field) is not None:
            setattr(task, field, args[field])
    ctx.session.add(task)
    await ctx.session.commit()
    await ctx.session.refresh(task)
    return {"updated": _task_dict(task)}


async def _create_document(ctx: ToolContext, args: dict):
    title = str(args.get("title") or "").strip()
    if not title:
        raise ToolError("title is required")
    doc = Document(
        workspace_id=ctx.workspace_id, title=title, doc_type="doc",
        content_raw=args.get("content") or "", created_by_id=ctx.user_id,
    )
    ctx.session.add(doc)
    await ctx.session.commit()
    await ctx.session.refresh(doc)
    return {"created": {"id": doc.id, "title": doc.title}}


async def _update_document(ctx: ToolContext, args: dict):
    doc = await _get_owned(ctx, Document, args.get("document_id"), "Document")
    if args.get("title") is not None:
        doc.title = args["title"]
    if args.get("content") is not None:
        doc.content_raw = args["content"]
    doc.updated_at = datetime.now(timezone.utc)
    ctx.session.add(doc)
    await ctx.session.commit()
    return {"updated": {"id": doc.id, "title": doc.title}}


async def _send_message(ctx: ToolContext, args: dict):
    channel = await _get_owned(ctx, Channel, args.get("channel_id"), "Channel")
    content = str(args.get("content") or "").strip()
    if not content:
        raise ToolError("content is required")
    msg = Message(channel_id=channel.id, sender_id=ctx.user_id, content=content)
    ctx.session.add(msg)
    await ctx.session.commit()
    await ctx.session.refresh(msg)
    return {"sent": {"id": msg.id, "channel": channel.name}}


# ---- delete tools ----

async def _delete_task(ctx: ToolContext, args: dict):
    task = await _get_owned(ctx, Task, args.get("task_id"), "Task")
    await ctx.session.delete(task)
    await ctx.session.commit()
    return {"deleted": {"task_id": task.id, "title": task.title}}


async def _delete_document(ctx: ToolContext, args: dict):
    doc = await _get_owned(ctx, Document, args.get("document_id"), "Document")
    await ctx.session.delete(doc)
    await ctx.session.commit()
    return {"deleted": {"document_id": doc.id, "title": doc.title}}


_ID = {"type": "integer"}

TOOLS: list[Tool] = [
    Tool("search_workspace", "read",
         "Full-text search across messages, tasks, documents and file names of this workspace. "
         "Matches words or word fragments of 3+ characters, ranked by relevance. "
         "Use it first when the user asks about workspace content.",
         _obj({
             "query": {"type": "string", "description": "Words to look for"},
             "kinds": {"type": "array", "items": {"type": "string", "enum": ["message", "task", "document", "file"]},
                       "description": "Limit to these content kinds"},
             "limit": {"type": "integer", "minimum": 1, "maximum": 50},
         }, ["query"]),
         _search),
    Tool("list_tasks", "read", "List tasks of the workspace, newest first.",
         _obj({"status": {"type": "string", "enum": TASK_STATUSES}}), _list_tasks),
    Tool("list_documents", "read", "List documents (title, type, size) without their content.",
         _obj({"doc_type": {"type": "string", "enum": ["doc", "mindmap", "canvas", "quiz"]}}), _list_documents),
    Tool("read_document", "read", "Read the full content of one document.",
         _obj({"document_id": _ID}, ["document_id"]), _read_document),
    Tool("list_channels", "read", "List chat channels.", _obj({}), _list_channels),
    Tool("read_messages", "read", "Read the latest messages of a chat channel.",
         _obj({"channel_id": _ID, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, ["channel_id"]),
         _read_messages),
    Tool("list_files", "read", "List uploaded files with their folder path, size and type.", _obj({}), _list_files),
    Tool("create_task", "write", "Create a task on the board.",
         _obj({
             "title": {"type": "string"}, "description": {"type": "string"},
             "status": {"type": "string", "enum": TASK_STATUSES},
             "priority": {"type": "string", "enum": TASK_PRIORITIES},
         }, ["title"]),
         _create_task),
    Tool("update_task", "write", "Change title, description, status or priority of a task.",
         _obj({
             "task_id": _ID, "title": {"type": "string"}, "description": {"type": "string"},
             "status": {"type": "string", "enum": TASK_STATUSES},
             "priority": {"type": "string", "enum": TASK_PRIORITIES},
         }, ["task_id"]),
         _update_task),
    Tool("create_document", "write", "Create a Markdown document.",
         _obj({"title": {"type": "string"}, "content": {"type": "string", "description": "Markdown"}}, ["title"]),
         _create_document),
    Tool("update_document", "write", "Replace the title and/or full content of a document.",
         _obj({"document_id": _ID, "title": {"type": "string"}, "content": {"type": "string"}}, ["document_id"]),
         _update_document),
    Tool("send_message", "write", "Post a message to a chat channel on behalf of the user.",
         _obj({"channel_id": _ID, "content": {"type": "string"}}, ["channel_id", "content"]),
         _send_message),
    Tool("delete_task", "delete", "Delete a task permanently.",
         _obj({"task_id": _ID}, ["task_id"]), _delete_task),
    Tool("delete_document", "delete", "Delete a document permanently.",
         _obj({"document_id": _ID}, ["document_id"]), _delete_document),
]

TOOLS_BY_NAME = {t.name: t for t in TOOLS}
