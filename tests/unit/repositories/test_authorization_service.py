"""AuthorizationService의 세션/환자 접근 판정. 참고: §13.1, §22.1, §25.1."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.report_generation.errors import UnauthorizedError
from app.services.authorization_service import AuthorizationService


def _mock_db(rows: list) -> AsyncMock:
    """db.execute()가 순서대로 rows를 반환하도록 하는 mock. 각 row는 tuple."""
    db = AsyncMock()
    results = []
    for row in rows:
        result = MagicMock()
        result.first.return_value = row
        results.append(result)
    db.execute = AsyncMock(side_effect=results)
    return db


@pytest.mark.asyncio
async def test_session_owner_allowed():
    db = _mock_db([("t1", "ACTIVE")])
    await AuthorizationService().ensure_session_access(db, "s1", "t1")


@pytest.mark.asyncio
async def test_session_non_owner_denied():
    db = _mock_db([("t1", "ACTIVE"), ("SLP",)])
    with pytest.raises(UnauthorizedError):
        await AuthorizationService().ensure_session_access(db, "s1", "t2")


@pytest.mark.asyncio
async def test_session_admin_bypass():
    db = _mock_db([("t1", "ACTIVE"), ("ADMIN",)])
    await AuthorizationService().ensure_session_access(db, "s1", "t2")


@pytest.mark.asyncio
async def test_session_deleted_denied_even_for_owner():
    db = _mock_db([("t1", "DELETED")])
    with pytest.raises(UnauthorizedError):
        await AuthorizationService().ensure_session_access(db, "s1", "t1")


@pytest.mark.asyncio
async def test_session_not_found_denied():
    db = _mock_db([None])
    with pytest.raises(UnauthorizedError):
        await AuthorizationService().ensure_session_access(db, "s1", "t1")


@pytest.mark.asyncio
async def test_patient_ref_current_slp_allowed():
    db = _mock_db([("t1",)])
    await AuthorizationService().ensure_patient_ref_access(db, "p1", "t1")


@pytest.mark.asyncio
async def test_patient_ref_transferred_owner_denied():
    # 환자가 t2에게 이관됨 - 예전 담당(t1)은 더 이상 접근 불가
    db = _mock_db([("t2",), ("SLP",)])
    with pytest.raises(UnauthorizedError):
        await AuthorizationService().ensure_patient_ref_access(db, "p1", "t1")
