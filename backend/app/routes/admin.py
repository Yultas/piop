import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select, delete, update
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.app.database import get_session
from backend.app.config import settings
from backend.app.models import (
    User, Workspace, WorkspaceMember, WorkspaceInvite, WorkspaceFile, WorkspaceFolder,
    Channel, Message, Task, Document,
    WorkspaceAIPermission, AIConversation, AIMessage
)
from backend.app.ai import llm
from backend.app.ai.agent import get_ai_settings, is_configured
from backend.app.auth import get_current_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])

class UserRoleUpdate(BaseModel):
    is_global_admin: bool

class WorkspaceQuotaUpdate(BaseModel):
    storage_quota_mb: int

class AISettingsUpdate(BaseModel):
    enabled: bool
    base_url: str
    model: str
    api_key: Optional[str] = None # None keeps the stored key, "" clears it

def ai_settings_payload(cfg) -> dict:
    return {
        "enabled": cfg.enabled,
        "base_url": cfg.base_url,
        "model": cfg.model,
        "has_api_key": bool(cfg.api_key),
        "api_key_hint": f"…{cfg.api_key[-4:]}" if len(cfg.api_key) > 8 else "",
        "configured": is_configured(cfg),
    }

@router.get("/users")
async def list_users(
    admin_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    stmt = select(User).order_by(User.created_at.desc())
    res = await session.execute(stmt)
    users = res.scalars().all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "is_global_admin": u.is_global_admin,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat()
        }
        for u in users
    ]

@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    req: UserRoleUpdate,
    admin_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    target = await session.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="admin.user_not_found")
        
    # Prevent removing global admin from oneself if last admin
    if target.id == admin_user.id and not req.is_global_admin:
        stmt = select(User).where(User.is_global_admin == True)
        res = await session.execute(stmt)
        admins = res.scalars().all()
        if len(admins) <= 1:
            raise HTTPException(status_code=400, detail="admin.cannot_demote_last_admin")

    target.is_global_admin = req.is_global_admin
    session.add(target)
    await session.commit()
    await session.refresh(target)
    return {
        "id": target.id,
        "username": target.username,
        "is_global_admin": target.is_global_admin
    }

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    target = await session.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="admin.user_not_found")
    if target.id == admin_user.id:
        raise HTTPException(status_code=400, detail="admin.cannot_delete_self")

    # Messages are personal: remove them, detaching replies and tasks that point at them
    own_messages = select(Message.id).where(Message.sender_id == user_id)
    await session.execute(
        update(Message).where(Message.thread_parent_id.in_(own_messages)).values(thread_parent_id=None)
    )
    await session.execute(
        update(Task).where(Task.origin_message_id.in_(own_messages)).values(origin_message_id=None)
    )
    await session.execute(delete(Message).where(Message.sender_id == user_id))

    # Workspace content stays and is handed over to the admin performing the deletion
    await session.execute(update(Task).where(Task.assignee_id == user_id).values(assignee_id=None))
    for model, column in (
        (Workspace, Workspace.created_by_id),
        (WorkspaceInvite, WorkspaceInvite.created_by_id),
        (WorkspaceFile, WorkspaceFile.uploader_id),
        (WorkspaceFolder, WorkspaceFolder.created_by_id),
        (Document, Document.created_by_id),
    ):
        await session.execute(update(model).where(column == user_id).values({column.key: admin_user.id}))

    # Device-bound invites must not let anyone reconnect as the deleted user
    await session.execute(
        update(WorkspaceInvite)
        .where(WorkspaceInvite.claimed_by_id == user_id)
        .values(claimed_by_id=None, status="REVOKED")
    )
    user_convs = select(AIConversation.id).where(AIConversation.user_id == user_id)
    await session.execute(delete(AIMessage).where(AIMessage.conversation_id.in_(user_convs)))
    await session.execute(delete(AIConversation).where(AIConversation.user_id == user_id))
    await session.execute(delete(WorkspaceMember).where(WorkspaceMember.user_id == user_id))
    await session.delete(target)
    await session.commit()
    return {"id": user_id, "deleted": True}

@router.get("/workspaces")
async def list_all_workspaces(
    admin_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    stmt = select(Workspace).order_by(Workspace.created_at.desc())
    res = await session.execute(stmt)
    workspaces = res.scalars().all()
    
    result = []
    for ws in workspaces:
        m_stmt = select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id)
        m_res = await session.execute(m_stmt)
        members = m_res.scalars().all()
        
        result.append({
            "id": ws.id,
            "name": ws.name,
            "description": ws.description,
            "storage_quota_bytes": ws.storage_quota_bytes,
            "storage_quota_mb": round(ws.storage_quota_bytes / 1048576, 1),
            "used_storage_bytes": ws.used_storage_bytes,
            "used_storage_mb": round(ws.used_storage_bytes / 1048576, 2),
            "percentage": round(ws.used_storage_bytes / ws.storage_quota_bytes * 100, 1) if ws.storage_quota_bytes > 0 else 0,
            "members_count": len(members),
            "created_at": ws.created_at.isoformat()
        })
    return result

@router.put("/workspaces/{workspace_id}/quota")
async def set_workspace_quota(
    workspace_id: int,
    req: WorkspaceQuotaUpdate,
    admin_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    ws = await session.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="workspace.not_found")
        
    ws.storage_quota_bytes = req.storage_quota_mb * 1024 * 1024
    session.add(ws)
    await session.commit()
    await session.refresh(ws)
    return {
        "id": ws.id,
        "storage_quota_bytes": ws.storage_quota_bytes,
        "storage_quota_mb": req.storage_quota_mb
    }

@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(
    workspace_id: int,
    admin_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    ws = await session.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="workspace.not_found")

    channel_ids = select(Channel.id).where(Channel.workspace_id == workspace_id)
    message_ids = select(Message.id).where(Message.channel_id.in_(channel_ids))

    # Children first: tasks may reference messages, replies reference parent messages
    await session.execute(delete(Task).where(Task.workspace_id == workspace_id))
    await session.execute(
        update(Message).where(Message.id.in_(message_ids)).values(thread_parent_id=None)
    )
    await session.execute(delete(Message).where(Message.channel_id.in_(channel_ids)))
    ws_convs = select(AIConversation.id).where(AIConversation.workspace_id == workspace_id)
    await session.execute(delete(AIMessage).where(AIMessage.conversation_id.in_(ws_convs)))
    for model in (
        AIConversation, WorkspaceAIPermission,
        Channel, Document, WorkspaceFile, WorkspaceFolder, WorkspaceInvite, WorkspaceMember,
    ):
        await session.execute(delete(model).where(model.workspace_id == workspace_id))
    await session.delete(ws)
    await session.commit()

    shutil.rmtree(Path(settings.UPLOAD_DIR) / str(workspace_id), ignore_errors=True)
    return {"id": workspace_id, "deleted": True}

@router.get("/ai-settings")
async def read_ai_settings(
    admin_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    return ai_settings_payload(await get_ai_settings(session))

@router.put("/ai-settings")
async def update_ai_settings(
    req: AISettingsUpdate,
    admin_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    cfg = await get_ai_settings(session)
    cfg.enabled = req.enabled
    cfg.base_url = req.base_url.strip()
    cfg.model = req.model.strip()
    if req.api_key is not None:
        cfg.api_key = req.api_key.strip()
    cfg.updated_at = datetime.now(timezone.utc)
    session.add(cfg)
    await session.commit()
    await session.refresh(cfg)
    return ai_settings_payload(cfg)

@router.post("/ai-settings/models")
async def list_ai_models(
    req: AISettingsUpdate,
    admin_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    """Check the connection with the submitted (unsaved) values and list available models."""
    stored = await get_ai_settings(session)
    probe = type(stored)(
        base_url=req.base_url.strip(),
        api_key=stored.api_key if req.api_key is None else req.api_key.strip(),
    )
    return {"models": await llm.list_models(probe)}
