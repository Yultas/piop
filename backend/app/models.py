from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    hashed_password: str
    is_global_admin: bool = Field(default=False)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)

class Workspace(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = Field(default="")
    storage_quota_bytes: int = Field(default=524288000) # 500 MB in bytes
    used_storage_bytes: int = Field(default=0)
    created_by_id: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utc_now)

class WorkspaceMember(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    role: str = Field(default="member") # "admin", "member"
    joined_at: datetime = Field(default_factory=utc_now)

class WorkspaceInvite(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    token: str = Field(index=True, unique=True)
    target_role: str = Field(default="member")
    created_by_id: int = Field(foreign_key="user.id")
    status: str = Field(default="ISSUED") # "ISSUED", "CLAIMED", "REVOKED"
    device_fingerprint_hash: Optional[str] = Field(default=None, index=True)
    claimed_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    claimed_at: Optional[datetime] = Field(default=None)
    expires_at: Optional[datetime] = Field(default=None)

class WorkspaceFolder(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    parent_id: Optional[int] = Field(default=None, foreign_key="workspacefolder.id", index=True)
    name: str
    created_by_id: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utc_now)

class WorkspaceFile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    folder_id: Optional[int] = Field(default=None, foreign_key="workspacefolder.id", index=True)
    file_name: str
    file_size_bytes: int
    mime_type: str
    file_path: str
    uploader_id: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utc_now)

class Channel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    name: str
    is_private: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)

class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    channel_id: int = Field(foreign_key="channel.id", index=True)
    sender_id: int = Field(foreign_key="user.id")
    thread_parent_id: Optional[int] = Field(default=None, foreign_key="message.id")
    content: str
    created_at: datetime = Field(default_factory=utc_now)

class Task(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    title: str
    description: Optional[str] = Field(default="")
    status: str = Field(default="todo") # "todo", "in_progress", "done"
    priority: str = Field(default="medium") # "low", "medium", "high"
    assignee_id: Optional[int] = Field(default=None, foreign_key="user.id")
    origin_message_id: Optional[int] = Field(default=None, foreign_key="message.id")
    due_date: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)

class Document(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    title: str
    doc_type: str = Field(default="doc") # "doc", "mindmap", "canvas", "quiz"
    content_raw: str = Field(default="")
    created_by_id: int = Field(foreign_key="user.id")
    updated_at: datetime = Field(default_factory=utc_now)

class AISettings(SQLModel, table=True):
    """Global OpenAI-compatible provider configuration (single row, id=1)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    enabled: bool = Field(default=False)
    base_url: str = Field(default="https://api.openai.com/v1")
    api_key: str = Field(default="")
    model: str = Field(default="")
    updated_at: datetime = Field(default_factory=utc_now)

class WorkspaceAIPermission(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    action: str
    mode: str = Field(default="off") # "off", "confirm", "auto"

class AIConversation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    title: str = Field(default="")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

class AIMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="aiconversation.id", index=True)
    role: str # "user", "assistant", "tool"
    content: Optional[str] = Field(default=None)
    tool_calls: Optional[str] = Field(default=None) # JSON, assistant only
    tool_call_id: Optional[str] = Field(default=None)
    tool_name: Optional[str] = Field(default=None)
    tool_args: Optional[str] = Field(default=None) # JSON
    status: Optional[str] = Field(default=None) # tool only: "pending", "done", "rejected", "error"
    created_at: datetime = Field(default_factory=utc_now)

class ApiToken(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str
    token_hash: str = Field(index=True, unique=True) # sha256 hex of the full token; the token itself is never stored
    prefix: str # first 12 chars of the token, shown in lists
    created_at: datetime = Field(default_factory=utc_now)
    last_used_at: Optional[datetime] = Field(default=None)
