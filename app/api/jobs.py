from fastapi import APIRouter, HTTPException
from app.schemas import JobCreateRequest, JobCreateResponse, JobStatusResponse, JobStatus
from app.utils.ids import generate_job_id

router = APIRouter()


@router.post("", response_model=JobCreateResponse)
async def create_job(request: JobCreateRequest):
    job_id = generate_job_id()
    # TODO: Job DB 저장, SQS 메시지 발행
    return JobCreateResponse(job_id=job_id, status=JobStatus.PENDING)


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str):
    # TODO: DB에서 Job 조회
    raise HTTPException(status_code=404, detail="job not found")
