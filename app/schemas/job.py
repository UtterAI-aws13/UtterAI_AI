from enum import Enum
from datetime import datetime
from pydantic import BaseModel


class JobStatus(str, Enum):
    PENDING = "PENDING"
    DOWNLOADING = "DOWNLOADING"
    PREPROCESSING = "PREPROCESSING"
    RUNNING_VAD = "RUNNING_VAD"
    RUNNING_DIARIZATION = "RUNNING_DIARIZATION"
    RUNNING_ASR = "RUNNING_ASR"
    ALIGNING = "ALIGNING"
    CALCULATING_METRICS = "CALCULATING_METRICS"
    RUNNING_RAG = "RUNNING_RAG"
    GENERATING_REPORT = "GENERATING_REPORT"
    SAVING_RESULT = "SAVING_RESULT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


class TargetSpeakerPolicy(str, Enum):
    AUTO_DETECT_CHILD = "AUTO_DETECT_CHILD"
    MANUAL = "MANUAL"
    ALL_SPEAKERS = "ALL_SPEAKERS"


class AudioInput(BaseModel):
    bucket: str
    key: str
    content_type: str = "audio/wav"


class JobOptions(BaseModel):
    language: str = "ko"
    enable_diarization: bool = True
    enable_rag: bool = True
    target_speaker_policy: TargetSpeakerPolicy = TargetSpeakerPolicy.AUTO_DETECT_CHILD


class JobMessage(BaseModel):
    job_id: str
    session_id: str
    user_id: str
    audio: AudioInput
    options: JobOptions = JobOptions()
    requested_at: datetime


class JobCreateRequest(BaseModel):
    session_id: str
    audio_s3_key: str
    options: JobOptions = JobOptions()


class JobCreateResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: float | None = None
    current_step: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class JobFailureInfo(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.FAILED
    failed_step: str
    error_code: str
    error_message: str
    retryable: bool = True
