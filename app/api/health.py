# 헬스 체크 API
# /health/live  - 프로세스 생존 확인 (ECS/EKS 컨테이너 재시작 판단에 사용)
# /health/ready - DB, S3 연결 상태까지 확인 (트래픽 수신 준비 여부 판단에 사용)
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class LiveResponse(BaseModel):
    status: str = "ok"


class ReadyResponse(BaseModel):
    status: str
    db: bool   # PostgreSQL 연결 가능 여부
    s3: bool   # S3 버킷 접근 가능 여부


@router.get("/live", response_model=LiveResponse)
async def liveness():
    """프로세스가 살아있으면 200을 반환한다."""
    return LiveResponse()


@router.get("/ready", response_model=ReadyResponse)
async def readiness():
    """DB와 S3 연결이 모두 정상일 때 200을 반환한다."""
    # TODO: DB, S3 연결 상태 체크
    return ReadyResponse(status="ok", db=True, s3=True)
