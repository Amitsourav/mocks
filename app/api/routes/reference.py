"""Reference-catalog endpoints for the cascading registration form.

All require a valid session (`get_current_user`) but NOT a completed profile —
the user is mid-registration when they fetch these. The data is served from the
config-driven reference tables so the catalog can grow without code changes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.db import get_pool
from app.schemas.user import CatalogExamOut, CountryOut, CurrentUser, MockCategoryOut, StateOut

router = APIRouter(prefix="/reference", tags=["reference"])


@router.get("/states", response_model=list[StateOut])
async def list_states(_: CurrentUser = Depends(get_current_user)) -> list[StateOut]:
    rows = await get_pool().fetch(
        "select code, name, kind from states order by position, name"
    )
    return [StateOut(**dict(r)) for r in rows]


@router.get("/countries", response_model=list[CountryOut])
async def list_countries(_: CurrentUser = Depends(get_current_user)) -> list[CountryOut]:
    rows = await get_pool().fetch(
        "select code, name from countries order by position, name"
    )
    return [CountryOut(**dict(r)) for r in rows]


@router.get("/mock-categories", response_model=list[MockCategoryOut])
async def list_mock_categories(_: CurrentUser = Depends(get_current_user)) -> list[MockCategoryOut]:
    rows = await get_pool().fetch(
        "select code, name from mock_categories where is_active = true order by position, name"
    )
    return [MockCategoryOut(**dict(r)) for r in rows]


@router.get("/mock-categories/{category_code}/exams", response_model=list[CatalogExamOut])
async def list_category_exams(
    category_code: str,
    _: CurrentUser = Depends(get_current_user),
) -> list[CatalogExamOut]:
    """The dependent dropdown: exam names available under a mock category."""
    pool = get_pool()
    category = await pool.fetchrow(
        "select id from mock_categories where code = $1 and is_active = true",
        category_code,
    )
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mock category not found")

    rows = await pool.fetch(
        """
        select code, name, requires_country, default_country_code
        from catalog_exams
        where category_id = $1 and is_active = true
        order by position, name
        """,
        category["id"],
    )
    return [CatalogExamOut(**dict(r)) for r in rows]
