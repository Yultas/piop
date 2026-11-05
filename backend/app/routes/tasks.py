from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.app.database import get_session
from backend.app.models import Workspace, WorkspaceMember, Task, Message, User
from backend.app.auth import get_current_user

router = APIRouter(prefix="/api/workspaces/{workspace_id}/tasks", tags=["tasks"])

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    status: Optional[str] = "todo"
    priority: Optional[str] = "medium"
    assignee_id: Optional[int] = None
    due_date: Optional[datetime] = None

class ConvertMessageToTask(BaseModel):
    message_id: int
    title: Optional[str] = None
    priority: Optional[str] = "medium"

class TaskStatusUpdate(BaseModel):
    status: str

async def verify_member(workspace_id: int, user: User, session: AsyncSession):
    if user.is_global_admin:
        return
    stmt = select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user.id
    )
    res = await session.execute(stmt)
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="workspace.access_denied")

@router.get("")
async def list_tasks(
    workspace_id: int,
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await verify_member(workspace_id, current_user, session)
    stmt = select(Task).where(Task.workspace_id == workspace_id)
    if status_filter:
        stmt = stmt.where(Task.status == status_filter)
    stmt = stmt.order_by(Task.created_at.desc())
    res = await session.execute(stmt)
    tasks = res.scalars().all()
    
    # Enrich with assignee username if present
    enriched = []
    for t in tasks:
        assignee_name = None
        if t.assignee_id:
            u = await session.get(User, t.assignee_id)
            if u:
                assignee_name = u.username
        enriched.append({
            "id": t.id,
            "workspace_id": t.workspace_id,
            "title": t.title,
            "description": t.description,
            "status": t.status,
            "priority": t.priority,
            "assignee_id": t.assignee_id,
            "assignee_username": assignee_name,
            "origin_message_id": t.origin_message_id,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "created_at": t.created_at.isoformat()
        })
    return enriched

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_task(
    workspace_id: int,
    req: TaskCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await verify_member(workspace_id, current_user, session)
    task = Task(
        workspace_id=workspace_id,
        title=req.title,
        description=req.description or "",
        status=req.status or "todo",
        priority=req.priority or "medium",
        assignee_id=req.assignee_id,
        # Dates without a timezone (e.g. "2026-11-12") are taken as UTC
        due_date=req.due_date.replace(tzinfo=timezone.utc) if req.due_date and req.due_date.tzinfo is None else req.due_date
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task

@router.post("/from-message", status_code=status.HTTP_201_CREATED)
async def create_task_from_message(
    workspace_id: int,
    req: ConvertMessageToTask,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await verify_member(workspace_id, current_user, session)
    msg = await session.get(Message, req.message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="tasks.message_not_found")
        
    # Derive title from message content if not provided
    title = req.title or (msg.content[:60] + "..." if len(msg.content) > 60 else msg.content)
    
    task = Task(
        workspace_id=workspace_id,
        title=title,
        description=f"> {msg.content}",
        status="todo",
        priority=req.priority or "medium",
        origin_message_id=msg.id,
        assignee_id=current_user.id
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task

@router.patch("/{task_id}/status")
async def update_task_status(
    workspace_id: int,
    task_id: int,
    req: TaskStatusUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await verify_member(workspace_id, current_user, session)
    task = await session.get(Task, task_id)
    if not task or task.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="tasks.not_found")
        
    task.status = req.status
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task

@router.delete("/{task_id}")
async def delete_task(
    workspace_id: int,
    task_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await verify_member(workspace_id, current_user, session)
    task = await session.get(Task, task_id)
    if not task or task.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="tasks.not_found")
    await session.delete(task)
    await session.commit()
    return {"ok": True}
