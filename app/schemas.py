"""Request/response schemas (allow-list models; no mass assignment)."""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str
    display_name: str


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str


class UpdateMeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str


class LoginResponse(BaseModel):
    token: str
    user: UserOut


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class MemberAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    role: str


class MemberRolePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: Optional[str] = None


class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    description: Optional[str] = None
    archived: Optional[bool] = None
    # workspace_id intentionally NOT a field: immutable (SEC-013)


class IssueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    title: str
    description: Optional[str] = None
    type: Optional[str] = None
    priority: Optional[str] = None
    assignee_id: Optional[str] = None
    due_date: Optional[str] = None


class IssuePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee_id: Optional[str] = None
    due_date: Optional[str] = None
    # project_id/workspace_id/creator_id not writable (SEC-013)


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str


class MemberOut(BaseModel):
    user_id: str
    display_name: str
    role: str
    email: Optional[str] = None


class PageOut(BaseModel):
    items: List[dict]
    page: int
    page_size: int
    total_items: int
    total_pages: int
