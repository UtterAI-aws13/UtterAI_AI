# Deterministic 노드/서비스가 발생시키는 타입 있는 실패.
# Phase 4의 Graph 노드 어댑터가 이 예외를 잡아 GraphState.failure_code/failure_detail로
# 변환하고 §12.3/§26.2 라우팅 규칙에 따라 FAILURE 또는 재시도로 보낸다.
from app.agents.report_generation.models.common import FailureCode


class ReportGenerationError(Exception):
    failure_code: FailureCode

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class UnauthorizedError(ReportGenerationError):
    failure_code = FailureCode.UNAUTHORIZED


class InvalidSessionStateError(ReportGenerationError):
    failure_code = FailureCode.INVALID_SESSION_STATE


class MissingConfirmedTranscriptError(ReportGenerationError):
    failure_code = FailureCode.MISSING_CONFIRMED_TRANSCRIPT


class DuplicateRunError(ReportGenerationError):
    failure_code = FailureCode.DUPLICATE_RUN


class MaliciousPayloadError(ReportGenerationError):
    failure_code = FailureCode.MALICIOUS_PAYLOAD
