# 분석 Job API
# POST /ai/jobs  - Backend가 음성 분석을 요청할 때 Job을 생성하고 job_id를 즉시 반환
# GET  /ai/jobs/{job_id} - 처리 단계와 진행 상태를 폴링할 때 사용
from fastapi import APIRouter, HTTPException
from app.schemas import JobCreateRequest, JobCreateResponse, JobStatusResponse, JobStatus
from app.utils.ids import generate_job_id

router = APIRouter()


@router.post("", response_model=JobCreateResponse)
async def create_job(request: JobCreateRequest):
    """분석 Job을 생성하고 SQS에 메시지를 발행한다.

    Worker가 SQS 메시지를 수신해 비동기로 분석을 처리하므로
    API는 job_id와 PENDING 상태만 즉시 반환한다.
    """
    job_id = generate_job_id()
    # TODO: Job DB 저장, SQS 메시지 발행
    return JobCreateResponse(job_id=job_id, status=JobStatus.PENDING)


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str):
    """DB에서 Job 상태를 조회한다. Backend가 완료 여부를 폴링하는 용도로 사용."""
    # TODO: DB에서 Job 조회
    raise HTTPException(status_code=404, detail="job not found")
