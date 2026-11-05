import hashlib
import secrets
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select, func
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.app.database import get_session
from backend.app.models import ApiToken, User
from backend.app.auth import get_session_user, API_TOKEN_PREFIX

router = APIRouter(prefix="/api/auth/tokens", tags=["auth"])

MAX_TOKENS_PER_USER = 20

class TokenCreate(BaseModel):
    name: str

def _summary(t: ApiToken) -> dict:
    return {
        "id": t.id, "name": t.name, "prefix": t.prefix,
        "created_at": t.created_at.isoformat(), "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
    }

@router.get("")
async def list_tokens(
    current_user: User = Depends(get_session_user),
    session: AsyncSession = Depends(get_session)
):
    stmt = select(ApiToken).where(ApiToken.user_id == current_user.id).order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
    return [_summary(t) for t in (await session.execute(stmt)).scalars().all()]

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_token(
    req: TokenCreate,
    current_user: User = Depends(get_session_user),
    session: AsyncSession = Depends(get_session)
):
    name = req.name.strip()
    if not 1 <= len(name) <= 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tokens.name_required")
    count = (await session.execute(
        select(func.count()).select_from(ApiToken).where(ApiToken.user_id == current_user.id)
    )).scalar_one()
    if count >= MAX_TOKENS_PER_USER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tokens.limit")

    # The full token is returned once here; only its hash is stored.
    token = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = ApiToken(
        user_id=current_user.id,
        name=name,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        prefix=token[:12],
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {**_summary(row), "token": token}

@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_token(
    token_id: int,
    current_user: User = Depends(get_session_user),
    session: AsyncSession = Depends(get_session)
):
    row = await session.get(ApiToken, token_id)
    if not row or row.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tokens.not_found")
    await session.delete(row)
    await session.commit()
    return None
