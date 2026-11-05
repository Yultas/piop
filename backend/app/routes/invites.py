import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.app.database import get_session
from backend.app.models import Workspace, WorkspaceInvite, WorkspaceMember, User
from backend.app.auth import get_current_user, create_user_token, hash_password, verify_password, set_session_cookie
from backend.app.ratelimit import ip_limiter, account_limiter, account_key, client_ip
from backend.app.fingerprint import compute_device_hash, verify_device_hash

router = APIRouter(prefix="/api/invites", tags=["invites"])

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def reserve_account(ip: str, ip_stamp: float, username: str) -> str:
    """Reserve a per-account guess slot before verifying a password for an existing user."""
    key = account_key(ip, username)
    try:
        account_limiter.acquire(key)
    except HTTPException:
        # Refused before any guess was made, so this request must not count against the IP.
        ip_limiter.release(ip, ip_stamp)
        raise
    return key

class CreateInviteRequest(BaseModel):
    workspace_id: int
    target_role: Optional[str] = "member"
    expires_in_days: Optional[int] = 7

class ClaimInviteRequest(BaseModel):
    username: str = Field(max_length=150)
    password: str = Field(max_length=1024)
    # Includes a canvas PNG data URL; its size depends on the client's fonts and often exceeds 8 KiB
    raw_fingerprint: str = Field(max_length=131072)

@router.post("")
async def create_invite(
    req: CreateInviteRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    ws = await session.get(Workspace, req.workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="workspace.not_found")
        
    if not current_user.is_global_admin:
        m_stmt = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws.id,
            WorkspaceMember.user_id == current_user.id
        )
        m_res = await session.execute(m_stmt)
        mem = m_res.scalar_one_or_none()
        if not mem or mem.role != "admin":
            raise HTTPException(status_code=403, detail="workspace.admin_required")

    token = secrets.token_urlsafe(32)
    # 0 or None -> Perpetual (Бессрочный инвайт)
    if req.expires_in_days is not None and req.expires_in_days > 0:
        expires_at = utc_now() + timedelta(days=req.expires_in_days)
    else:
        expires_at = None
    
    invite = WorkspaceInvite(
        workspace_id=ws.id,
        token=token,
        target_role=req.target_role or "member",
        created_by_id=current_user.id,
        status="ISSUED",
        expires_at=expires_at
    )
    session.add(invite)
    await session.commit()
    await session.refresh(invite)
    
    return {
        "invite_id": invite.id,
        "token": invite.token,
        "workspace_id": ws.id,
        "workspace_name": ws.name,
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        "is_perpetual": invite.expires_at is None
    }

@router.get("/{token}")
async def inspect_invite(token: str, session: AsyncSession = Depends(get_session)):
    stmt = select(WorkspaceInvite).where(WorkspaceInvite.token == token)
    res = await session.execute(stmt)
    invite = res.scalar_one_or_none()
    
    if not invite:
        raise HTTPException(status_code=404, detail="auth.invite.not_found")
    if invite.status == "REVOKED":
        raise HTTPException(status_code=400, detail="auth.invite.revoked")
    if invite.expires_at is not None and utc_now() > invite.expires_at:
        raise HTTPException(status_code=400, detail="auth.invite.expired")
        
    ws = await session.get(Workspace, invite.workspace_id)
    return {
        "token": invite.token,
        "workspace_id": invite.workspace_id,
        "workspace_name": ws.name if ws else "Workspace",
        "status": invite.status,
        "is_claimed": invite.status == "CLAIMED",
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        "is_perpetual": invite.expires_at is None
    }

@router.post("/{token}/claim")
async def claim_invite(
    token: str,
    req: ClaimInviteRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session)
):
    ip = client_ip(request)
    ip_stamp = ip_limiter.acquire(ip)

    stmt = select(WorkspaceInvite).where(WorkspaceInvite.token == token)
    res = await session.execute(stmt)
    invite = res.scalar_one_or_none()

    # Unknown token counts as a guess; the three rejections below are not, so they give the IP slot back.
    if not invite:
        raise HTTPException(status_code=404, detail="auth.invite.not_found")
    if invite.status == "REVOKED":
        ip_limiter.release(ip, ip_stamp)
        raise HTTPException(status_code=400, detail="auth.invite.revoked")
    if invite.expires_at is not None and utc_now() > invite.expires_at:
        ip_limiter.release(ip, ip_stamp)
        raise HTTPException(status_code=400, detail="auth.invite.expired")

    ws = await session.get(Workspace, invite.workspace_id)
    if not ws:
        ip_limiter.release(ip, ip_stamp)
        raise HTTPException(status_code=404, detail="workspace.not_found")

    device_hash = compute_device_hash(req.raw_fingerprint)

    # 1. CASE: Invite is already CLAIMED
    if invite.status == "CLAIMED":
        if invite.device_fingerprint_hash != device_hash:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="auth.invite.device_locked"
            )
        user = await session.get(User, invite.claimed_by_id)
        if not user:
            raise HTTPException(status_code=401, detail="auth.invalid_credentials")
        account = reserve_account(ip, ip_stamp, user.username)
        if not verify_password(req.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="auth.invalid_credentials")
        account_limiter.reset(account)
        ip_limiter.release(ip, ip_stamp)

        access_token = create_user_token(user)
        set_session_cookie(response, request, access_token)
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "workspace_id": ws.id,
            "message": "reconnected"
        }

    # 2. CASE: Invite is fresh ISSUED
    u_stmt = select(User).where(User.username == req.username)
    u_res = await session.execute(u_stmt)
    user = u_res.scalar_one_or_none()
    
    if user:
        account = reserve_account(ip, ip_stamp, user.username)
        if not verify_password(req.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="auth.invalid_credentials")
        account_limiter.reset(account)
    else:
        user = User(
            username=req.username,
            hashed_password=hash_password(req.password),
            is_global_admin=False
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    mem_stmt = select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == ws.id,
        WorkspaceMember.user_id == user.id
    )
    mem_res = await session.execute(mem_stmt)
    if not mem_res.scalar_one_or_none():
        new_mem = WorkspaceMember(
            workspace_id=ws.id,
            user_id=user.id,
            role=invite.target_role or "member"
        )
        session.add(new_mem)

    invite.status = "CLAIMED"
    invite.device_fingerprint_hash = device_hash
    invite.claimed_by_id = user.id
    invite.claimed_at = utc_now()
    session.add(invite)
    
    await session.commit()
    ip_limiter.release(ip, ip_stamp)

    access_token = create_user_token(user)
    set_session_cookie(response, request, access_token)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "workspace_id": ws.id,
        "message": "claimed_and_bound"
    }
