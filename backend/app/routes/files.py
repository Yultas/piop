import os
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.background import BackgroundTask
from backend.app.config import settings
from backend.app.database import get_session
from backend.app.models import Workspace, WorkspaceMember, WorkspaceFile, WorkspaceFolder, User
from backend.app.auth import get_current_user

router = APIRouter(prefix="/api/workspaces/{workspace_id}/files", tags=["files"])

class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None

class FolderRename(BaseModel):
    name: str

class ItemsSelection(BaseModel):
    file_ids: List[int] = []
    folder_ids: List[int] = []

class MoveRequest(ItemsSelection):
    target_folder_id: Optional[int] = None

async def check_workspace_access(workspace_id: int, user: User, session: AsyncSession) -> Workspace:
    ws = await session.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="workspace.not_found")
    if not user.is_global_admin:
        stmt = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id
        )
        res = await session.execute(stmt)
        if not res.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="workspace.access_denied")
    return ws

def format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    return f"{round(size / 1024, 1)} KB" if size < 1048576 else f"{round(size / 1048576, 2)} MB"

def serialize_file(f: WorkspaceFile) -> dict:
    return {
        "id": f.id,
        "folder_id": f.folder_id,
        "file_name": f.file_name,
        "file_size_bytes": f.file_size_bytes,
        "file_size_formatted": format_size(f.file_size_bytes),
        "mime_type": f.mime_type,
        "created_at": f.created_at.isoformat()
    }

def clean_name(name: str) -> str:
    """Folder names become archive paths, so keep them to a single safe segment."""
    name = (name or "").strip().replace("/", "-").replace("\\", "-")
    if not name or name in (".", ".."):
        raise HTTPException(status_code=400, detail="files.invalid_folder_name")
    return name[:120]

async def all_folders(workspace_id: int, session: AsyncSession) -> dict[int, WorkspaceFolder]:
    rows = (await session.execute(
        select(WorkspaceFolder).where(WorkspaceFolder.workspace_id == workspace_id)
    )).scalars().all()
    return {f.id: f for f in rows}

async def get_folder(workspace_id: int, folder_id: Optional[int], session: AsyncSession) -> Optional[WorkspaceFolder]:
    if folder_id is None:
        return None
    folder = await session.get(WorkspaceFolder, folder_id)
    if not folder or folder.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="files.folder_not_found")
    return folder

def folder_path(folder_id: Optional[int], folders: dict[int, WorkspaceFolder]) -> list[WorkspaceFolder]:
    path = []
    while folder_id is not None and folder_id in folders:
        path.append(folders[folder_id])
        folder_id = folders[folder_id].parent_id
    return list(reversed(path))

def descendant_ids(root_ids: list[int], folders: dict[int, WorkspaceFolder]) -> set[int]:
    """The given folders plus everything nested inside them."""
    result, frontier = set(root_ids), list(root_ids)
    while frontier:
        current = frontier.pop()
        for f in folders.values():
            if f.parent_id == current and f.id not in result:
                result.add(f.id)
                frontier.append(f.id)
    return result

async def ensure_unique_name(workspace_id: int, parent_id: Optional[int], name: str, session: AsyncSession, exclude_id: Optional[int] = None):
    siblings = (await session.execute(select(WorkspaceFolder).where(
        WorkspaceFolder.workspace_id == workspace_id, WorkspaceFolder.parent_id == parent_id
    ))).scalars().all()
    if any(f.name.lower() == name.lower() and f.id != exclude_id for f in siblings):
        raise HTTPException(status_code=409, detail="files.folder_exists")

def remove_from_disk(path: str):
    try:
        os.remove(path)
    except OSError:
        pass

@router.get("")
async def list_files(
    workspace_id: int,
    folder_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    ws = await check_workspace_access(workspace_id, current_user, session)
    await get_folder(workspace_id, folder_id, session)
    folders = await all_folders(workspace_id, session)

    files = (await session.execute(
        select(WorkspaceFile)
        .where(WorkspaceFile.workspace_id == workspace_id, WorkspaceFile.folder_id == folder_id)
        .order_by(WorkspaceFile.file_name)
    )).scalars().all()

    # Folder sizes and item counts include everything nested inside
    all_files = (await session.execute(
        select(WorkspaceFile.folder_id, WorkspaceFile.file_size_bytes).where(WorkspaceFile.workspace_id == workspace_id)
    )).all()
    subfolders = sorted((f for f in folders.values() if f.parent_id == folder_id), key=lambda f: f.name.lower())
    folder_entries = []
    for sub in subfolders:
        inside = descendant_ids([sub.id], folders)
        size = sum(s for fid, s in all_files if fid in inside)
        count = sum(1 for fid, _ in all_files if fid in inside)
        folder_entries.append({
            "id": sub.id, "name": sub.name, "items_count": count + len(inside) - 1,
            "size_bytes": size, "size_formatted": format_size(size), "created_at": sub.created_at.isoformat()
        })

    return {
        "storage_quota_bytes": ws.storage_quota_bytes,
        "used_storage_bytes": ws.used_storage_bytes,
        "quota_mb": round(ws.storage_quota_bytes / (1024 * 1024), 2),
        "used_mb": round(ws.used_storage_bytes / (1024 * 1024), 2),
        "percentage": round((ws.used_storage_bytes / ws.storage_quota_bytes * 100), 1) if ws.storage_quota_bytes > 0 else 0,
        "folder_id": folder_id,
        "breadcrumbs": [{"id": f.id, "name": f.name} for f in folder_path(folder_id, folders)],
        "folders": folder_entries,
        "files": [serialize_file(f) for f in files]
    }

@router.get("/folders")
async def list_all_folders(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Flat list of every folder with its full path, for pickers such as "move to"."""
    await check_workspace_access(workspace_id, current_user, session)
    folders = await all_folders(workspace_id, session)
    entries = [
        {"id": f.id, "parent_id": f.parent_id, "name": f.name,
         "path": "/".join(p.name for p in folder_path(f.id, folders))}
        for f in folders.values()
    ]
    return sorted(entries, key=lambda e: e["path"].lower())

@router.post("/folders", status_code=status.HTTP_201_CREATED)
async def create_folder(
    workspace_id: int,
    req: FolderCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await check_workspace_access(workspace_id, current_user, session)
    await get_folder(workspace_id, req.parent_id, session)
    name = clean_name(req.name)
    await ensure_unique_name(workspace_id, req.parent_id, name, session)
    folder = WorkspaceFolder(workspace_id=workspace_id, parent_id=req.parent_id, name=name, created_by_id=current_user.id)
    session.add(folder)
    await session.commit()
    await session.refresh(folder)
    return {"id": folder.id, "name": folder.name, "parent_id": folder.parent_id}

@router.patch("/folders/{folder_id}")
async def rename_folder(
    workspace_id: int,
    folder_id: int,
    req: FolderRename,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await check_workspace_access(workspace_id, current_user, session)
    folder = await get_folder(workspace_id, folder_id, session)
    name = clean_name(req.name)
    await ensure_unique_name(workspace_id, folder.parent_id, name, session, exclude_id=folder.id)
    folder.name = name
    session.add(folder)
    await session.commit()
    return {"id": folder.id, "name": folder.name, "parent_id": folder.parent_id}

@router.post("/move")
async def move_items(
    workspace_id: int,
    req: MoveRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await check_workspace_access(workspace_id, current_user, session)
    await get_folder(workspace_id, req.target_folder_id, session)
    folders = await all_folders(workspace_id, session)

    for fid in req.folder_ids:
        if fid not in folders:
            raise HTTPException(status_code=404, detail="files.folder_not_found")
    if req.target_folder_id is not None and req.target_folder_id in descendant_ids(req.folder_ids, folders):
        raise HTTPException(status_code=400, detail="files.move_into_itself")
    for fid in req.folder_ids:
        await ensure_unique_name(workspace_id, req.target_folder_id, folders[fid].name, session, exclude_id=fid)
        folders[fid].parent_id = req.target_folder_id
        session.add(folders[fid])

    for file_id in req.file_ids:
        f = await session.get(WorkspaceFile, file_id)
        if not f or f.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="files.not_found")
        f.folder_id = req.target_folder_id
        session.add(f)

    await session.commit()
    return {"ok": True}

@router.delete("/folders/{folder_id}")
async def delete_folder(
    workspace_id: int,
    folder_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Delete a folder with everything inside it and free the storage it used."""
    ws = await check_workspace_access(workspace_id, current_user, session)
    await get_folder(workspace_id, folder_id, session)
    folders = await all_folders(workspace_id, session)
    doomed = descendant_ids([folder_id], folders)

    files = (await session.execute(
        select(WorkspaceFile).where(WorkspaceFile.workspace_id == workspace_id, WorkspaceFile.folder_id.in_(doomed))
    )).scalars().all()
    freed = sum(f.file_size_bytes for f in files)
    for f in files:
        remove_from_disk(f.file_path)
        await session.delete(f)
    await session.flush()

    # Children before parents
    for fid in sorted(doomed, key=lambda i: len(folder_path(i, folders)), reverse=True):
        await session.delete(folders[fid])

    ws.used_storage_bytes = max(0, ws.used_storage_bytes - freed)
    session.add(ws)
    await session.commit()
    return {"ok": True, "deleted_files": len(files), "used_storage_bytes": ws.used_storage_bytes}

@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_file(
    workspace_id: int,
    file: UploadFile = File(...),
    folder_id: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    ws = await check_workspace_access(workspace_id, current_user, session)
    await get_folder(workspace_id, folder_id, session)

    # Read file content or get size
    content = await file.read()
    file_size = len(content)

    # Check Storage Quota Limit
    if ws.used_storage_bytes + file_size > ws.storage_quota_bytes:
        used_mb = round(ws.used_storage_bytes / 1048576, 1)
        quota_mb = round(ws.storage_quota_bytes / 1048576, 1)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"workspace.storage.limit_exceeded (Used: {used_mb}MB / Quota: {quota_mb}MB)"
        )

    # Save file on disk in upload directory
    upload_dir = Path(settings.UPLOAD_DIR) / str(workspace_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # A random prefix keeps same-named uploads from overwriting each other
    safe_filename = f"{uuid.uuid4().hex}_{os.path.basename(file.filename or 'unnamed_file')}"
    dest_path = upload_dir / safe_filename

    with open(dest_path, "wb") as f:
        f.write(content)

    # Create DB record and update quota
    db_file = WorkspaceFile(
        workspace_id=workspace_id,
        folder_id=folder_id,
        file_name=file.filename or "file",
        file_size_bytes=file_size,
        mime_type=file.content_type or "application/octet-stream",
        file_path=str(dest_path),
        uploader_id=current_user.id
    )
    session.add(db_file)

    ws.used_storage_bytes += file_size
    session.add(ws)

    await session.commit()
    await session.refresh(db_file)

    return {
        "id": db_file.id,
        "folder_id": db_file.folder_id,
        "file_name": db_file.file_name,
        "file_size_bytes": db_file.file_size_bytes,
        "mime_type": db_file.mime_type,
        "used_storage_bytes": ws.used_storage_bytes
    }

def build_zip(entries: list[tuple[str, str]], empty_dirs: list[str]) -> str:
    """Write (disk path, archive path) pairs into a temporary zip and return its path."""
    fd, tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    used: set[str] = set()
    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for d in empty_dirs:
            zf.writestr(d.rstrip("/") + "/", "")
        for disk_path, arc_path in entries:
            # Same-named files in one folder get " (2)", " (3)"… suffixes
            stem, ext = os.path.splitext(arc_path)
            candidate, n = arc_path, 2
            while candidate.lower() in used:
                candidate, n = f"{stem} ({n}){ext}", n + 1
            used.add(candidate.lower())
            if os.path.exists(disk_path):
                zf.write(disk_path, candidate)
    return tmp_path

@router.post("/archive")
async def download_archive(
    workspace_id: int,
    req: ItemsSelection,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Zip the selected files and folders (with their contents), keeping the folder structure."""
    ws = await check_workspace_access(workspace_id, current_user, session)
    if not req.file_ids and not req.folder_ids:
        raise HTTPException(status_code=400, detail="files.nothing_selected")
    folders = await all_folders(workspace_id, session)
    for fid in req.folder_ids:
        if fid not in folders:
            raise HTTPException(status_code=404, detail="files.folder_not_found")

    entries: list[tuple[str, str]] = []
    empty_dirs: list[str] = []
    for file_id in req.file_ids:
        f = await session.get(WorkspaceFile, file_id)
        if not f or f.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="files.not_found")
        entries.append((f.file_path, f.file_name))

    for root_id in req.folder_ids:
        root_depth = len(folder_path(root_id, folders)) - 1
        inside = descendant_ids([root_id], folders)
        files = (await session.execute(
            select(WorkspaceFile).where(WorkspaceFile.workspace_id == workspace_id, WorkspaceFile.folder_id.in_(inside))
        )).scalars().all()
        non_empty = set()
        for f in files:
            rel = "/".join(p.name for p in folder_path(f.folder_id, folders)[root_depth:])
            entries.append((f.file_path, f"{rel}/{f.file_name}"))
            non_empty.update(p.id for p in folder_path(f.folder_id, folders))
        for fid in inside:
            if fid not in non_empty:
                empty_dirs.append("/".join(p.name for p in folder_path(fid, folders)[root_depth:]))

    tmp_path = await run_in_threadpool(build_zip, entries, empty_dirs)

    if len(req.folder_ids) == 1 and not req.file_ids:
        archive_name = f"{folders[req.folder_ids[0]].name}.zip"
    else:
        archive_name = f"{ws.name}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.zip"
    return FileResponse(
        path=tmp_path,
        filename=archive_name,
        media_type="application/zip",
        background=BackgroundTask(remove_from_disk, tmp_path)
    )

@router.get("/{file_id}/download")
async def download_file(
    workspace_id: int,
    file_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    await check_workspace_access(workspace_id, current_user, session)
    file_record = await session.get(WorkspaceFile, file_id)
    if not file_record or file_record.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="files.not_found")

    if not os.path.exists(file_record.file_path):
        raise HTTPException(status_code=404, detail="files.missing_on_disk")

    # mime_type is client-claimed: force download and forbid rendering/sniffing on our origin
    return FileResponse(
        path=file_record.file_path,
        filename=file_record.file_name,
        media_type=file_record.mime_type,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"}
    )

@router.delete("/{file_id}")
async def delete_file(
    workspace_id: int,
    file_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    ws = await check_workspace_access(workspace_id, current_user, session)
    file_record = await session.get(WorkspaceFile, file_id)
    if not file_record or file_record.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="files.not_found")

    # Free disk space
    remove_from_disk(file_record.file_path)

    # Deduct from used quota
    ws.used_storage_bytes = max(0, ws.used_storage_bytes - file_record.file_size_bytes)
    session.add(ws)
    await session.delete(file_record)
    await session.commit()

    return {"ok": True, "used_storage_bytes": ws.used_storage_bytes}
