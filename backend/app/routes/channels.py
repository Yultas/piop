from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.app.database import get_session
from backend.app.models import Workspace, WorkspaceMember, Channel, Message, User
from backend.app.auth import get_current_user

router = APIRouter(prefix="/api/workspaces/{workspace_id}/channels", tags=["channels"])

class ChannelCreate(BaseModel):
    name: str
    is_private: Optional[bool] = False

class MessageCreate(BaseModel):
    content: str
    thread_parent_id: Optional[int] = None

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
async def list_channels(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await verify_member(workspace_id, current_user, session)
    stmt = select(Channel).where(Channel.workspace_id == workspace_id)
    res = await session.execute(stmt)
    channels = res.scalars().all()
    return channels

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_channel(
    workspace_id: int,
    req: ChannelCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await verify_member(workspace_id, current_user, session)
    channel = Channel(
        workspace_id=workspace_id,
        name=req.name.lower().replace(" ", "-"),
        is_private=req.is_private or False
    )
    session.add(channel)
    await session.commit()
    await session.refresh(channel)
    return channel

@router.get("/{channel_id}/messages")
async def get_messages(
    workspace_id: int,
    channel_id: int,
    parent_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await verify_member(workspace_id, current_user, session)
    
    # Filter root messages or thread replies
    if parent_id is not None:
        stmt = (
            select(Message, User.username)
            .join(User, User.id == Message.sender_id)
            .where(Message.channel_id == channel_id, Message.thread_parent_id == parent_id)
            .order_by(Message.created_at.asc())
        )
    else:
        stmt = (
            select(Message, User.username)
            .join(User, User.id == Message.sender_id)
            .where(Message.channel_id == channel_id, Message.thread_parent_id == None)
            .order_by(Message.created_at.asc())
        )
    
    res = await session.execute(stmt)
    rows = res.all()
    
    messages = []
    for msg, username in rows:
        # Count replies in thread
        reply_stmt = select(func.count(Message.id)).where(Message.thread_parent_id == msg.id)
        reply_res = await session.execute(reply_stmt)
        reply_count = reply_res.scalar() or 0
        
        messages.append({
            "id": msg.id,
            "channel_id": msg.channel_id,
            "sender_id": msg.sender_id,
            "sender_username": username,
            "thread_parent_id": msg.thread_parent_id,
            "content": msg.content,
            "reply_count": reply_count,
            "created_at": msg.created_at.isoformat()
        })
    return messages

@router.post("/{channel_id}/messages", status_code=status.HTTP_201_CREATED)
async def send_message(
    workspace_id: int,
    channel_id: int,
    req: MessageCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await verify_member(workspace_id, current_user, session)
    msg = Message(
        channel_id=channel_id,
        sender_id=current_user.id,
        thread_parent_id=req.thread_parent_id,
        content=req.content
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return {
        "id": msg.id,
        "channel_id": msg.channel_id,
        "sender_id": msg.sender_id,
        "sender_username": current_user.username,
        "thread_parent_id": msg.thread_parent_id,
        "content": msg.content,
        "reply_count": 0,
        "created_at": msg.created_at.isoformat()
    }
