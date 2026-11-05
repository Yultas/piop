from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.app.config import settings
from backend.app.database import get_session
from backend.app.models import User, Workspace, WorkspaceMember, Channel
from backend.app.auth import get_current_user, get_current_admin

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

class WorkspaceCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    storage_quota_mb: Optional[int] = None

class QuotaUpdate(BaseModel):
    storage_quota_mb: int

@router.get("")
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    if current_user.is_global_admin:
        stmt = select(Workspace)
    else:
        stmt = (
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == current_user.id)
        )
    result = await session.execute(stmt)
    workspaces = result.scalars().all()
    
    # Enrich with user's role
    res = []
    for ws in workspaces:
        m_stmt = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws.id,
            WorkspaceMember.user_id == current_user.id
        )
        m_res = await session.execute(m_stmt)
        member = m_res.scalar_one_or_none()
        role = "admin" if current_user.is_global_admin else (member.role if member else "none")
        res.append({
            "id": ws.id,
            "name": ws.name,
            "description": ws.description,
            "storage_quota_bytes": ws.storage_quota_bytes,
            "used_storage_bytes": ws.used_storage_bytes,
            "role": role,
            "created_at": ws.created_at.isoformat()
        })
    return res

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    req: WorkspaceCreate,
    admin_user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    # Determine quota in bytes
    quota_mb = req.storage_quota_mb or settings.DEFAULT_WORKSPACE_STORAGE_QUOTA_MB
    quota_bytes = quota_mb * 1024 * 1024
    
    workspace = Workspace(
        name=req.name,
        description=req.description or "",
        storage_quota_bytes=quota_bytes,
        used_storage_bytes=0,
        created_by_id=admin_user.id
    )
    session.add(workspace)
    await session.commit()
    await session.refresh(workspace)
    
    # Add creator as admin member
    membership = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=admin_user.id,
        role="admin"
    )
    session.add(membership)
    
    # Create default channel
    default_channel = Channel(
        workspace_id=workspace.id,
        name="general",
        is_private=False
    )
    session.add(default_channel)
    
    await session.commit()
    return workspace

@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    ws = await session.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="workspace.not_found")
        
    # Check access
    if not current_user.is_global_admin:
        m_stmt = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws.id,
            WorkspaceMember.user_id == current_user.id
        )
        m_res = await session.execute(m_stmt)
        if not m_res.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="workspace.access_denied")
            
    # Count members
    count_stmt = select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id)
    count_res = await session.execute(count_stmt)
    members = count_res.scalars().all()
    
    return {
        "id": ws.id,
        "name": ws.name,
        "description": ws.description,
        "storage_quota_bytes": ws.storage_quota_bytes,
        "used_storage_bytes": ws.used_storage_bytes,
        "member_count": len(members),
        "created_at": ws.created_at.isoformat()
    }

@router.put("/{workspace_id}/quota")
async def update_quota(
    workspace_id: int,
    req: QuotaUpdate,
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
