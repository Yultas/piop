"""
Full-text search over workspace content backed by SQLite FTS5.

The index is kept in sync by SQLite triggers, so every write path (API routes,
admin cascades, AI tools) updates it without extra code. The trigram tokenizer
matches substrings of 3+ characters in any language; the rowid packs the
source kind and id so trigger updates are point lookups.
"""
import re
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlmodel.ext.asyncio.session import AsyncSession

KIND_CODES = {"message": 1, "task": 2, "document": 3, "file": 4}
KIND_NAMES = {code: name for name, code in KIND_CODES.items()}
KIND_BITS = 8


def _norm(expr: str) -> str:
    """SQL expression folding ё into е (FTS5 folds case but not this letter)."""
    return f"replace(replace(coalesce({expr}, ''), 'ё', 'е'), 'Ё', 'Е')"


# Per source: table, kind, SQL for workspace_id, title and body given a row alias
_SOURCES = [
    (
        "message", "message",
        "(SELECT workspace_id FROM channel WHERE channel.id = {r}.channel_id)",
        "(SELECT '#' || name FROM channel WHERE channel.id = {r}.channel_id)",
        "{r}.content",
    ),
    ("task", "task", "{r}.workspace_id", "{r}.title", "{r}.description"),
    ("document", "document", "{r}.workspace_id", "{r}.title", "{r}.content_raw"),
    ("workspacefile", "file", "{r}.workspace_id", "{r}.file_name", "{r}.mime_type"),
]


def _insert_sql(kind: str, ws: str, title: str, body: str, r: str) -> str:
    code = KIND_CODES[kind]
    return (
        "INSERT INTO search_index(rowid, title, body, workspace_id, kind, ref_id) VALUES ("
        f"{r}.id * {KIND_BITS} + {code}, {_norm(title.format(r=r))}, {_norm(body.format(r=r))}, "
        f"{ws.format(r=r)}, '{kind}', {r}.id);"
    )


def _schema_statements() -> list[str]:
    stmts = [
        "CREATE VIRTUAL TABLE search_index USING fts5("
        "title, body, workspace_id UNINDEXED, kind UNINDEXED, ref_id UNINDEXED, "
        "tokenize='trigram remove_diacritics 1')"
    ]
    for table, kind, ws, title, body in _SOURCES:
        code = KIND_CODES[kind]
        delete = f"DELETE FROM search_index WHERE rowid = old.id * {KIND_BITS} + {code};"
        stmts += [
            f"CREATE TRIGGER search_{table}_ai AFTER INSERT ON {table} BEGIN "
            f"{_insert_sql(kind, ws, title, body, 'new')} END",
            f"CREATE TRIGGER search_{table}_ad AFTER DELETE ON {table} BEGIN {delete} END",
            f"CREATE TRIGGER search_{table}_au AFTER UPDATE ON {table} BEGIN "
            f"{delete} {_insert_sql(kind, ws, title, body, 'new')} END",
        ]
    return stmts


def _backfill_statements() -> list[str]:
    stmts = []
    for table, kind, ws, title, body in _SOURCES:
        code = KIND_CODES[kind]
        stmts.append(
            "INSERT INTO search_index(rowid, title, body, workspace_id, kind, ref_id) "
            f"SELECT s.id * {KIND_BITS} + {code}, {_norm(title.format(r='s'))}, "
            f"{_norm(body.format(r='s'))}, {ws.format(r='s')}, '{kind}', s.id FROM {table} s"
        )
    return stmts


async def init_search_index(conn: AsyncConnection) -> None:
    """Create the FTS table and triggers once, indexing any existing rows."""
    exists = await conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'search_index'")
    )
    if exists.first():
        return
    for stmt in _schema_statements() + _backfill_statements():
        await conn.execute(text(stmt))


_WORD = re.compile(r"\w+", re.UNICODE)


def _normalize_query(query: str) -> str:
    return query.replace("ё", "е").replace("Ё", "Е")


async def search_workspace(
    session: AsyncSession,
    workspace_id: int,
    query: str,
    kinds: Optional[list[str]] = None,
    limit: int = 20,
) -> list[dict]:
    """
    Rank workspace content by relevance (BM25, title weighted 5x over body).

    Words of 3+ characters go through the FTS index; shorter words, which the
    trigram index cannot match, are applied as substring filters on the hits.
    """
    words = _WORD.findall(_normalize_query(query))
    long_words = [w for w in words if len(w) >= 3]
    short_words = [w.lower() for w in words if len(w) < 3]
    if not words:
        return []

    params: dict = {"ws": workspace_id, "limit": max(1, min(limit, 50))}
    where = ["workspace_id = :ws"]
    if kinds:
        valid = [k for k in kinds if k in KIND_CODES]
        if valid:
            where.append("kind IN (" + ", ".join(f"'{k}'" for k in valid) + ")")
    for i, w in enumerate(short_words):
        params[f"s{i}"] = f"%{w}%"
        where.append(f"(lower(title) LIKE :s{i} OR lower(body) LIKE :s{i})")

    if long_words:
        params["q"] = " AND ".join('"' + w.replace('"', '""') + '"' for w in long_words)
        sql = (
            "SELECT kind, ref_id, title, "
            "snippet(search_index, 1, '«', '»', '…', 24) AS snippet, "
            "bm25(search_index, 5.0, 1.0) AS rank "
            "FROM search_index WHERE search_index MATCH :q AND "
            + " AND ".join(where)
            + " ORDER BY rank LIMIT :limit"
        )
    else:
        sql = (
            "SELECT kind, ref_id, title, substr(body, 1, 160) AS snippet, 0 AS rank "
            "FROM search_index WHERE " + " AND ".join(where) + " LIMIT :limit"
        )

    rows = (await session.execute(text(sql), params)).mappings().all()
    return [
        {"kind": r["kind"], "id": r["ref_id"], "title": r["title"], "snippet": r["snippet"]}
        for r in rows
    ]
