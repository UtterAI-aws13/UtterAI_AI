# 헬스 체크 API
# /health/live  - 프로세스 생존 확인 (ECS/EKS 컨테이너 재시작 판단에 사용)
# /health/ready - DB, S3 연결 상태까지 확인 (트래픽 수신 준비 여부 판단에 사용)
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.storage.db import engine

router = APIRouter()


class LiveResponse(BaseModel):
    status: str = "ok"


class ReadyResponse(BaseModel):
    status: str
    db: bool
    s3: bool


@router.get("/live", response_model=LiveResponse)
async def liveness():
    """프로세스가 살아있으면 200을 반환한다."""
    return LiveResponse()


@router.get("/ready", response_model=ReadyResponse)
async def readiness():
    """DB와 S3 연결이 모두 정상일 때 200을 반환한다."""
    db_ok = False
    s3_ok = False

    try:
        async with AsyncSession(engine) as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    try:
        s3 = boto3.client("s3", region_name=settings.aws_region)
        s3.head_bucket(Bucket=settings.s3_bucket_audio)
        s3_ok = True
    except (BotoCoreError, ClientError):
        pass

    status = "ok" if (db_ok and s3_ok) else "degraded"
    return ReadyResponse(status=status, db=db_ok, s3=s3_ok)
