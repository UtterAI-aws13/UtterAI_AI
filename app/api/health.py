from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class LiveResponse(BaseModel):
    status: str = "ok"


class ReadyResponse(BaseModel):
    status: str
    db: bool
    s3: bool


@router.get("/live", response_model=LiveResponse)
async def liveness():
    return LiveResponse()


@router.get("/ready", response_model=ReadyResponse)
async def readiness():
    # TODO: DB, S3 연결 상태 체크
    return ReadyResponse(status="ok", db=True, s3=True)
