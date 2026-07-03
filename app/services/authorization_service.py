# session_id / patient_ref_id에 대한 therapist_id 접근 권한 검증.
# UtterAI_BE의 app/core/authorization.py::ensure_session_access /
# ensure_patient_ref_access와 동일한 판정 로직을 읽기 전용으로 미러링한다.
# 권한 검증은 prompt가 아니라 이 계층에서 강제한다 (§13.1, §22.1).
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.report_generation.errors import UnauthorizedError

_ADMIN_ROLE = "ADMIN"
_DELETED_SESSION_STATUS = "DELETED"


async def _get_user_role(db: AsyncSession, user_id: str) -> str | None:
    row = await db.execute(
        text("SELECT role FROM users WHERE id = CAST(:user_id AS uuid)"),
        {"user_id": user_id},
    )
    record = row.first()
    return record[0] if record else None


class AuthorizationService:
    async def ensure_session_access(
        self, db: AsyncSession, session_id: str, therapist_id: str
    ) -> None:
        """therapist_id가 session_id에 접근 가능한지 검증한다.

        ADMIN은 모든 세션에 접근 가능하다. SLP는 자신이 담당(slp_id)인
        세션에만 접근 가능하다. 삭제된 세션은 접근 불가로 취급한다.
        """
        row = await db.execute(
            text("SELECT slp_id, status FROM sessions WHERE id = CAST(:session_id AS uuid)"),
            {"session_id": session_id},
        )
        record = row.first()
        if record is None or record[1] == _DELETED_SESSION_STATUS:
            raise UnauthorizedError(f"session {session_id} not found or deleted")

        slp_id, _status = record
        if str(slp_id) == therapist_id:
            return

        role = await _get_user_role(db, therapist_id)
        if role == _ADMIN_ROLE:
            return

        raise UnauthorizedError(
            f"therapist {therapist_id} has no access to session {session_id}"
        )

    async def ensure_patient_ref_access(
        self, db: AsyncSession, patient_ref_id: str, therapist_id: str
    ) -> None:
        """therapist_id가 patient_ref_id(현재 담당 치료사 기준)에 접근 가능한지 검증한다.

        환자가 다른 치료사에게 이관된 경우 current_slp_id만 접근 가능하다
        (sessions.slp_id가 아니라 patient_refs.current_slp_id를 기준으로 한다).
        """
        row = await db.execute(
            text("SELECT current_slp_id FROM patient_refs WHERE id = CAST(:patient_ref_id AS uuid)"),
            {"patient_ref_id": patient_ref_id},
        )
        record = row.first()
        if record is None:
            raise UnauthorizedError(f"patient_ref {patient_ref_id} not found")

        if str(record[0]) == therapist_id:
            return

        role = await _get_user_role(db, therapist_id)
        if role == _ADMIN_ROLE:
            return

        raise UnauthorizedError(
            f"therapist {therapist_id} has no access to patient_ref {patient_ref_id}"
        )
