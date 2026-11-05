from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.app.database import get_session
from backend.app.models import Workspace, WorkspaceMember, Document, User
from backend.app.auth import get_current_user

router = APIRouter(prefix="/api/workspaces/{workspace_id}/documents", tags=["documents"])

class DocumentCreate(BaseModel):
    title: str
    doc_type: str # "doc", "mindmap", "canvas", "quiz"
    content_raw: Optional[str] = ""

class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    content_raw: str

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
async def list_documents(
    workspace_id: int,
    doc_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await verify_member(workspace_id, current_user, session)
    stmt = select(Document).where(Document.workspace_id == workspace_id)
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    stmt = stmt.order_by(Document.updated_at.desc())
    res = await session.execute(stmt)
    docs = res.scalars().all()
    return docs

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_document(
    workspace_id: int,
    req: DocumentCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await verify_member(workspace_id, current_user, session)
    doc = Document(
        workspace_id=workspace_id,
        title=req.title,
        doc_type=req.doc_type,
        content_raw=req.content_raw or "",
        created_by_id=current_user.id
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc

@router.get("/{document_id}")
async def get_document(
    workspace_id: int,
    document_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await verify_member(workspace_id, current_user, session)
    doc = await session.get(Document, document_id)
    if not doc or doc.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="documents.not_found")
    return doc

@router.put("/{document_id}")
async def update_document(
    workspace_id: int,
    document_id: int,
    req: DocumentUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await verify_member(workspace_id, current_user, session)
    doc = await session.get(Document, document_id)
    if not doc or doc.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="documents.not_found")
        
    if req.title is not None:
        doc.title = req.title
    doc.content_raw = req.content_raw
    doc.updated_at = datetime.now(timezone.utc)
    
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc

@router.delete("/{document_id}")
async def delete_document(
    workspace_id: int,
    document_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await verify_member(workspace_id, current_user, session)
    doc = await session.get(Document, document_id)
    if not doc or doc.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="documents.not_found")
    await session.delete(doc)
    await session.commit()
    return {"ok": True}
