"""
MCP endpoint (Streamable HTTP, stateless, JSON responses only) for external AI agents.

Agents get the same tools as the in-app assistant, with the rights of the authenticated user
in each workspace. Workspace AI-settings modes "off" block them as well.
"""
import copy
import json
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.app.database import get_session
from backend.app.models import User, Workspace, WorkspaceMember
from backend.app.auth import get_current_user
from backend.app.ai.agent import execute_tool, get_modes
from backend.app.ai.tools import TOOLS, TOOLS_BY_NAME, Tool, ToolContext

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
PROTOCOL_DEFAULT = "2025-06-18"
SERVER_INFO = {"name": "piop", "version": "1.0.0"}
INSTRUCTIONS = "Call list_workspaces first, then pass its workspace_id to every other tool."
KIND_ANNOTATIONS = {
    "read": {"readOnlyHint": True},
    "write": {"readOnlyHint": False, "destructiveHint": False},
    "delete": {"readOnlyHint": False, "destructiveHint": True},
}
WORKSPACE_PROPERTY = {"type": "integer", "description": "Workspace id from list_workspaces"}
LIST_WORKSPACES_TOOL = {
    "name": "list_workspaces",
    "description": "List the workspaces you can access, with your role in each.",
    "inputSchema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    "annotations": {"readOnlyHint": True},
}

class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code

def _result(msg_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}

def _error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

def _tool_result(text: str, is_error: bool) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}

def _tool_entry(tool: Tool) -> dict:
    # Deep copy: the shared TOOLS definitions are used by the in-app assistant and must not change.
    schema = copy.deepcopy(tool.parameters)
    schema["properties"] = {"workspace_id": dict(WORKSPACE_PROPERTY), **schema["properties"]}
    schema["required"] = ["workspace_id", *schema["required"]]
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": schema,
        "annotations": dict(KIND_ANNOTATIONS[tool.kind]),
    }

async def _member_roles(session: AsyncSession, user: User) -> dict[int, str]:
    rows = (await session.execute(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id))).scalars().all()
    return {m.workspace_id: m.role for m in rows}

async def _list_workspaces(session: AsyncSession, user: User) -> list[dict]:
    roles = await _member_roles(session, user)
    stmt = select(Workspace).order_by(Workspace.id)
    if not user.is_global_admin:
        stmt = stmt.where(Workspace.id.in_(list(roles)))
    workspaces = (await session.execute(stmt)).scalars().all()
    return [
        {"id": ws.id, "name": ws.name, "description": ws.description or "", "role": roles.get(ws.id, "admin")}
        for ws in workspaces
    ]

async def _can_access(session: AsyncSession, user: User, workspace_id) -> bool:
    if not isinstance(workspace_id, int) or isinstance(workspace_id, bool):
        return False
    if await session.get(Workspace, workspace_id) is None:
        return False
    if user.is_global_admin:
        return True
    member = (await session.execute(select(WorkspaceMember.id).where(
        WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user.id,
    ))).first()
    return member is not None

async def _call_tool(params: dict, user: User, session: AsyncSession) -> dict:
    name = params.get("name")
    args = params.get("arguments") or {}
    if not isinstance(name, str) or not isinstance(args, dict):
        raise RpcError(-32602, "Invalid params")
    if name == "list_workspaces":
        return _tool_result(json.dumps(await _list_workspaces(session, user), ensure_ascii=False), False)
    if name not in TOOLS_BY_NAME:
        raise RpcError(-32602, f"Unknown tool: {name}")

    workspace_id = args.get("workspace_id")
    if not await _can_access(session, user, workspace_id):
        return _tool_result(f"workspace {workspace_id} not found or access denied", True)
    modes = await get_modes(session, workspace_id)
    if modes.get(name, "off") == "off":
        return _tool_result(f"action {name} is disabled for AI in this workspace (workspace AI settings)", True)

    # "confirm" runs too: the MCP client does its own confirmation.
    tool_args = {k: v for k, v in args.items() if k != "workspace_id"}
    ctx = ToolContext(session=session, user_id=user.id, workspace_id=workspace_id)
    status_, text = await execute_tool(ctx, name, tool_args)
    return _tool_result(text, status_ == "error")

async def _run_method(method: str, params: dict, user: User, session: AsyncSession):
    if method == "initialize":
        requested = params.get("protocolVersion")
        return {
            "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_DEFAULT,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [LIST_WORKSPACES_TOOL, *(_tool_entry(t) for t in TOOLS)]}
    if method == "tools/call":
        return await _call_tool(params, user, session)
    raise RpcError(-32601, "Method not found")

async def _dispatch(msg, user: User, session: AsyncSession) -> dict | None:
    if not isinstance(msg, dict) or not isinstance(msg.get("method"), str):
        return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
    if "id" not in msg:
        return None  # notification, e.g. notifications/initialized: no response
    params = msg.get("params", {})
    if not isinstance(params, dict):
        return _error(msg["id"], -32602, "Invalid params")
    try:
        return _result(msg["id"], await _run_method(msg["method"], params, user, session))
    except RpcError as exc:
        return _error(msg["id"], exc.code, str(exc))

@router.post("")
async def mcp_endpoint(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(status_code=400, content=_error(None, -32700, "Parse error"))

    if isinstance(body, list):
        if not body:
            return JSONResponse(status_code=400, content=_error(None, -32600, "Invalid Request"))
        replies = []
        for msg in body:
            reply = await _dispatch(msg, user, session)
            if reply is not None:
                replies.append(reply)
        return JSONResponse(replies) if replies else Response(status_code=202)

    reply = await _dispatch(body, user, session)
    if reply is None:
        return Response(status_code=202)
    return JSONResponse(reply)
