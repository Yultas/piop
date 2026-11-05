from datetime import datetime, timedelta, timezone
from typing import Optional
import hashlib
import jwt
import bcrypt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.app.config import settings
from backend.app.database import get_session
from backend.app.models import ApiToken, User, utc_now

security = HTTPBearer(auto_error=False)

SESSION_COOKIE = "piop_session"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
API_TOKEN_PREFIX = "piop_"
API_TOKEN_TOUCH_SECONDS = 60

def hash_password(password: str) -> str:
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def _created_stamp(user: User) -> int:
    # Microseconds since the epoch; created_at comes back from SQLite without tzinfo, but it is UTC.
    created = user.created_at.replace(tzinfo=timezone.utc)
    return (created - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(microseconds=1)

def create_user_token(user: User) -> str:
    # SQLite reuses the ids of deleted users, so the token is bound to this account's creation time too.
    return create_access_token({"sub": str(user.id), "username": user.username, "uct": _created_stamp(user)})

def set_session_cookie(response: Response, request: Request, token: str) -> None:
    # Secure follows the scheme nginx reports, so plain HTTP over a VPN still gets the cookie back.
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="strict",
        path="/api",
        secure=https,
    )

def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/api")

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    session: AsyncSession = Depends(get_session)
) -> User:
    request.state.api_token_id = None
    if credentials:
        token = credentials.credentials
        if token.startswith(API_TOKEN_PREFIX):
            return await _user_from_api_token(request, token, session)
    else:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="auth.unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # A custom header forces a CORS preflight, which fails since CORS is off.
        # Defense in depth on top of SameSite=Strict.
        if request.method not in SAFE_METHODS and request.headers.get("x-piop-csrf") != "1":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="auth.csrf")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth.invalid_token")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth.invalid_token")

    user = await session.get(User, int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth.user_not_found")
    if payload.get("uct") != _created_stamp(user):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth.invalid_token")
    return user

async def _user_from_api_token(request: Request, token: str, session: AsyncSession) -> User:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = (await session.execute(select(ApiToken).where(ApiToken.token_hash == digest))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth.invalid_token")
    user = await session.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth.user_not_found")
    # Throttled: at most one write per minute per token, not one per request.
    now = utc_now()
    if row.last_used_at is None or now - row.last_used_at.replace(tzinfo=timezone.utc) > timedelta(seconds=API_TOKEN_TOUCH_SECONDS):
        row.last_used_at = now
        session.add(row)
        await session.commit()
    request.state.api_token_id = row.id
    return user

async def get_session_user(request: Request, user: User = Depends(get_current_user)) -> User:
    # A leaked API token must not be able to mint or list other tokens, so these routes need a real login.
    if request.state.api_token_id is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="auth.session_required")
    return user

async def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_global_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="auth.forbidden_admin_only")
    return current_user
