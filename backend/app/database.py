from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

# Columns added after a table first shipped; create_all does not alter existing tables
_ADDED_COLUMNS = [
    ("workspacefile", "folder_id", "INTEGER REFERENCES workspacefolder(id)"),
]

async def _add_missing_columns(conn):
    for table, column, ddl in _ADDED_COLUMNS:
        rows = await conn.execute(text(f"PRAGMA table_info({table})"))
        if column not in {r[1] for r in rows}:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        if "sqlite" in settings.DATABASE_URL:
            await _add_missing_columns(conn)
            from backend.app.search import init_search_index
            await init_search_index(conn)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
