import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.config import settings, ensure_secrets
from backend.app.database import init_db, async_session_factory
from backend.app.seed import seed_initial_data

from backend.app.routes.auth import router as auth_router
from backend.app.routes.workspaces import router as workspaces_router
from backend.app.routes.invites import router as invites_router
from backend.app.routes.files import router as files_router
from backend.app.routes.channels import router as channels_router
from backend.app.routes.tasks import router as tasks_router
from backend.app.routes.documents import router as documents_router
from backend.app.routes.board_ws import router as board_ws_router
from backend.app.routes.typst import router as typst_router
from backend.app.routes.admin import router as admin_router
from backend.app.routes.ai import router as ai_router
from backend.app.routes.tokens import router as tokens_router
from backend.app.routes.mcp import router as mcp_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_secrets(settings)

    # Ensure uploads directory
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    
    # Init DB
    await init_db()
    
    # Seed superadmin
    async with async_session_factory() as session:
        await seed_initial_data(session)
        
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan
)

# Frontend is served same-origin via nginx / Vite proxy, so CORS stays off unless CORS_ORIGINS is set.
if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth_router)
app.include_router(workspaces_router)
app.include_router(invites_router)
app.include_router(files_router)
app.include_router(channels_router)
app.include_router(tasks_router)
app.include_router(documents_router)
app.include_router(board_ws_router)
app.include_router(typst_router)
app.include_router(admin_router)
app.include_router(ai_router)
app.include_router(tokens_router)
app.include_router(mcp_router)

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": settings.PROJECT_NAME}
