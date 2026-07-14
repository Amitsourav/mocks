from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CurrentUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    auth_user_id: UUID
    full_name: str | None
    email: str | None
    phone: str | None
    address: str | None
    target_country: str | None
    target_examination_id: UUID | None
    role: str
    profile_completed: bool


class ProfileUpdate(BaseModel):
    full_name: str
    email: str | None = None
    address: str | None = None
    target_country: str
    target_examination_id: UUID | None = None
