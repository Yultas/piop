from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.app.database import get_session
from backend.app.models import User
from backend.app.auth import (
    verify_password, hash_password, create_user_token, get_current_user,
    set_session_cookie, clear_session_cookie,
)
from backend.app.ratelimit import account_limiter, ip_limiter, account_key, client_ip

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginRequest(BaseModel):
    username: str = Field(max_length=150)
    password: str = Field(max_length=1024)

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

@router.post("/login", response_model=LoginResponse)
async def login(
    req: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session)
):
    ip = client_ip(request)
    key = account_key(ip, req.username)
    ip_stamp = ip_limiter.acquire(ip)
    try:
        account_limiter.acquire(key)
    except HTTPException:
        # Refused before any guess was made, so this request must not count against the IP.
        ip_limiter.release(ip, ip_stamp)
        raise

    stmt = select(User).where(User.username == req.username)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="auth.invalid_credentials"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="auth.account_disabled"
        )

    token = create_user_token(user)
    account_limiter.reset(key)
    ip_limiter.release(ip, ip_stamp)
    set_session_cookie(response, request, token)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "is_global_admin": user.is_global_admin
        }
    }

@router.post("/logout")
async def logout(response: Response):
    clear_session_cookie(response)
    return {"status": "ok"}

@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "is_global_admin": current_user.is_global_admin
    }
