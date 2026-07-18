from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CurrentUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    auth_user_id: UUID
    full_name: str | None
    email: str | None
    phone: str | None
    role: str
    profile_completed: bool
    # cascading registration selections (codes into the reference tables)
    state_code: str | None
    mock_category_code: str | None
    catalog_exam_code: str | None
    target_country_code: str | None


class ProfileUpdate(BaseModel):
    full_name: str = Field(min_length=1)
    phone: str = Field(min_length=1)
    state_code: str
    mock_category_code: str
    catalog_exam_code: str
    # required only when the chosen exam requires a country; otherwise ignored
    target_country_code: str | None = None


# ---- Reference catalog response models ----

class StateOut(BaseModel):
    code: str
    name: str
    kind: str


class CountryOut(BaseModel):
    code: str
    name: str


class MockCategoryOut(BaseModel):
    code: str
    name: str


class CatalogExamOut(BaseModel):
    code: str
    name: str
    requires_country: bool
    default_country_code: str | None
