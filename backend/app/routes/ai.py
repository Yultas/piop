import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.app.database import get_session
from backend.app.models import (
    User, Workspace, WorkspaceMember, WorkspaceAIPermission, AIConversation, AIMessage
)
from backend.app.auth import get_current_user
from backend.app.ai.agent import (
    get_ai_settings, get_modes, has_pending, is_configured, resolve_action, run_agent
)
from backend.app.ai.tools import MODES, TOOLS, TOOLS_BY_NAME
from backend.app.search import search_workspace

router = APIRouter(prefix="/api/workspaces/{workspace_id}/ai", tags=["ai"])

class PermissionsUpdate(BaseModel):
    modes: dict[str, str]

class ConversationCreate(BaseModel):
    title: Optional[str] = ""

class AskRequest(BaseModel):
    content: str

async def load_workspace(workspace_id: int, user: User, session: AsyncSession) -> tuple[Workspace, bool]:
    """Return the workspace and whether the user may manage its AI permissions."""
    ws = await session.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="workspace.not_found")
    if user.is_global_admin:
        return ws, True
    member = (await session.execute(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user.id
    ))).scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=403, detail="workspace.access_denied")
    return ws, member.role == "admin"

async def load_conversation(conversation_id: int, workspace_id: int, user: User, session: AsyncSession) -> AIConversation:
    conv = await session.get(AIConversation, conversation_id)
    if not conv or conv.workspace_id != workspace_id or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="ai.conversation_not_found")
    return conv

async def require_configured(session: AsyncSession):
    if not is_configured(await get_ai_settings(session)):
        raise HTTPException(status_code=400, detail="ai.not_configured")

def serialize_message(m: AIMessage) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "tool_name": m.tool_name,
        "tool_kind": TOOLS_BY_NAME[m.tool_name].kind if m.tool_name in TOOLS_BY_NAME else None,
        "tool_args": json.loads(m.tool_args) if m.tool_args else None,
        "status": m.status,
        "created_at": m.created_at.isoformat(),
    }

async def conversation_payload(conv_id: int, session: AsyncSession) -> dict:
    rows = (await session.execute(
        select(AIMessage).where(AIMessage.conversation_id == conv_id).order_by(AIMessage.id)
    )).scalars().all()
    # Assistant turns that only carry tool calls have nothing to show
    visible = [m for m in rows if not (m.role == "assistant" and not m.content)]
    return {
        "conversation_id": conv_id,
        "messages": [serialize_message(m) for m in visible],
        "pending": any(m.status == "pending" for m in rows),
    }

@router.get("/status")
async def ai_status(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    _, can_manage = await load_workspace(workspace_id, current_user, session)
    cfg = await get_ai_settings(session)
    return {"configured": is_configured(cfg), "model": cfg.model, "can_manage": can_manage}

@router.get("/permissions")
async def get_permissions(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await load_workspace(workspace_id, current_user, session)
    modes = await get_modes(session, workspace_id)
    return [{"action": t.name, "kind": t.kind, "mode": modes[t.name]} for t in TOOLS]

@router.put("/permissions")
async def set_permissions(
    workspace_id: int,
    req: PermissionsUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    _, can_manage = await load_workspace(workspace_id, current_user, session)
    if not can_manage:
        raise HTTPException(status_code=403, detail="workspace.admin_required")
    for action, mode in req.modes.items():
        if action not in TOOLS_BY_NAME or mode not in MODES:
            raise HTTPException(status_code=400, detail="ai.invalid_permission")

    existing = {
        p.action: p for p in (await session.execute(
            select(WorkspaceAIPermission).where(WorkspaceAIPermission.workspace_id == workspace_id)
        )).scalars().all()
    }
    for action, mode in req.modes.items():
        perm = existing.get(action) or WorkspaceAIPermission(workspace_id=workspace_id, action=action)
        perm.mode = mode
        session.add(perm)
    await session.commit()
    modes = await get_modes(session, workspace_id)
    return [{"action": t.name, "kind": t.kind, "mode": modes[t.name]} for t in TOOLS]

@router.get("/search")
async def search(
    workspace_id: int,
    q: str,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await load_workspace(workspace_id, current_user, session)
    return await search_workspace(session, workspace_id, q, limit=limit)

@router.get("/conversations")
async def list_conversations(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await load_workspace(workspace_id, current_user, session)
    convs = (await session.execute(
        select(AIConversation)
        .where(AIConversation.workspace_id == workspace_id, AIConversation.user_id == current_user.id)
        .order_by(AIConversation.updated_at.desc())
    )).scalars().all()
    return [{"id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat()} for c in convs]

@router.post("/conversations", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    workspace_id: int,
    req: ConversationCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await load_workspace(workspace_id, current_user, session)
    conv = AIConversation(workspace_id=workspace_id, user_id=current_user.id, title=req.title or "")
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return {"id": conv.id, "title": conv.title, "updated_at": conv.updated_at.isoformat()}

@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    workspace_id: int,
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await load_workspace(workspace_id, current_user, session)
    conv = await load_conversation(conversation_id, workspace_id, current_user, session)
    await session.execute(delete(AIMessage).where(AIMessage.conversation_id == conv.id))
    await session.delete(conv)
    await session.commit()
    return {"ok": True}

@router.get("/conversations/{conversation_id}/messages")
async def get_conversation(
    workspace_id: int,
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await load_workspace(workspace_id, current_user, session)
    conv = await load_conversation(conversation_id, workspace_id, current_user, session)
    return await conversation_payload(conv.id, session)

@router.post("/conversations/{conversation_id}/messages")
async def ask(
    workspace_id: int,
    conversation_id: int,
    req: AskRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    ws, _ = await load_workspace(workspace_id, current_user, session)
    conv = await load_conversation(conversation_id, workspace_id, current_user, session)
    await require_configured(session)
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="ai.empty_message")
    if await has_pending(session, conv.id):
        raise HTTPException(status_code=409, detail="ai.pending_actions")

    if not conv.title:
        conv.title = content[:60]
        session.add(conv)
    session.add(AIMessage(conversation_id=conv.id, role="user", content=content))
    await session.commit()

    conv_id = conv.id
    await run_agent(session, conv, current_user, ws)
    return await conversation_payload(conv_id, session)

async def _resolve(workspace_id, conversation_id, message_id, approve, current_user, session):
    ws, _ = await load_workspace(workspace_id, current_user, session)
    conv = await load_conversation(conversation_id, workspace_id, current_user, session)
    await require_configured(session)
    row = await session.get(AIMessage, message_id)
    if not row or row.conversation_id != conv.id or row.status != "pending":
        raise HTTPException(status_code=404, detail="ai.action_not_found")
    conv_id = conv.id
    await resolve_action(session, conv, row, approve, current_user, ws)
    return await conversation_payload(conv_id, session)

@router.post("/conversations/{conversation_id}/actions/{message_id}/approve")
async def approve_action(
    workspace_id: int,
    conversation_id: int,
    message_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    return await _resolve(workspace_id, conversation_id, message_id, True, current_user, session)

@router.post("/conversations/{conversation_id}/actions/{message_id}/reject")
async def reject_action(
    workspace_id: int,
    conversation_id: int,
    message_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    return await _resolve(workspace_id, conversation_id, message_id, False, current_user, session)
