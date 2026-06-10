# 분석 Job의 상태 흐름과 요청/응답 스키마 정의
# Backend → SQS → AI Worker 로 이어지는 비동기 Job 처리의 계약(contract)
from enum import Enum
from datetime import datetime
from pydantic import BaseModel


class JobStatus(str, Enum):
    """분석 Job이 거치는 처리 단계. Worker는 각 단계 진입 시 DB에 상태를 업데이트한다."""
    PENDING = "PENDING"                       # Job 생성 완료, Worker 미처리
    DOWNLOADING = "DOWNLOADING"               # S3에서 음성 다운로드 중
    PREPROCESSING = "PREPROCESSING"           # ffmpeg 변환, 포맷 검사 중
    RUNNING_VAD = "RUNNING_VAD"               # Silero VAD 추론 중
    RUNNING_DIARIZATION = "RUNNING_DIARIZATION"  # pyannote 화자 분리 중
    RUNNING_ASR = "RUNNING_ASR"               # Whisper STT 추론 중
    ALIGNING = "ALIGNING"                     # VAD + 화자 + STT 결과 정렬 중
    CALCULATING_METRICS = "CALCULATING_METRICS"  # MLU, NDW, NTW, TTR 계산 중
    RUNNING_RAG = "RUNNING_RAG"               # pgvector 문서 검색 중
    GENERATING_REPORT = "GENERATING_REPORT"   # EXAONE SOAP Note 초안 생성 중
    SAVING_RESULT = "SAVING_RESULT"           # S3/RDS 저장 중
    COMPLETED = "COMPLETED"                   # 전체 파이프라인 완료
    FAILED = "FAILED"                         # 오류로 중단
    RETRYING = "RETRYING"                     # 재시도 중
    CANCELLED = "CANCELLED"                   # BE에서 취소 요청됨


class TargetSpeakerPolicy(str, Enum):
    """아동 화자를 어떻게 식별할지 결정하는 정책."""
    AUTO_DETECT_CHILD = "AUTO_DETECT_CHILD"  # 발화량/길이 규칙으로 자동 추정
    MANUAL = "MANUAL"                         # 치료사가 직접 지정
    ALL_SPEAKERS = "ALL_SPEAKERS"             # 전체 화자 지표를 모두 출력


class AudioInput(BaseModel):
    """SQS 메시지에 포함되는 S3 오디오 파일 위치 정보."""
    bucket: str
    key: str
    content_type: str = "audio/wav"


class JobOptions(BaseModel):
    """분석 파이프라인 동작을 제어하는 옵션."""
    language: str = "ko"
    enable_diarization: bool = True           # False면 화자 분리 생략, 전체를 UNKNOWN 처리
    enable_rag: bool = True                   # False면 RAG 검색 및 리포트 생성 생략
    target_speaker_policy: TargetSpeakerPolicy = TargetSpeakerPolicy.AUTO_DETECT_CHILD
    template_id: str | None = None            # 리포트 생성에 사용할 템플릿 ID (BE에서 전달)


class JobMessage(BaseModel):
    """SQS 메시지 또는 Worker 내부 Job 메시지 스키마."""
    job_id: str
    session_id: str
    audio_file_id: str
    user_id: str
    audio: AudioInput
    options: JobOptions = JobOptions()
    requested_at: datetime


class JobCreateRequest(BaseModel):
    """POST /ai/jobs 요청 바디. Backend가 분석 시작을 요청할 때 사용."""
    session_id: str
    audio_s3_key: str
    options: JobOptions = JobOptions()


class JobCreateResponse(BaseModel):
    """POST /ai/jobs 응답. job_id를 받아 이후 상태를 폴링한다."""
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    """GET /ai/jobs/{job_id} 응답. 현재 처리 단계와 오류 정보를 포함."""
    job_id: str
    status: JobStatus
    progress: float | None = None             # 0.0 ~ 1.0, 선택적 진행률
    current_step: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class JobFailureInfo(BaseModel):
    """분석 실패 시 RDS에 저장하는 오류 상세 정보."""
    job_id: str
    status: JobStatus = JobStatus.FAILED
    failed_step: str                          # 실패한 JobStatus 단계명
    error_code: str                           # 예: ASR_FAILED, AUDIO_TOO_SHORT
    error_message: str
    retryable: bool = True


class MLGpuMessage(BaseModel):
    """cpu-worker → audio-ml-queue 발행 메시지. ML GPU Worker가 수신한다."""
    job_id: str
    session_id: str
    audio_file_id: str
    wav_s3_key: str       # 전처리된 WAV S3 경로
    vad_s3_key: str       # VAD 결과 JSON S3 경로
    options: JobOptions = JobOptions()


class LLMMessage(BaseModel):
    """ml-gpu-worker → llm-queue 발행 메시지. LLM GPU Worker가 수신한다."""
    job_id: str
    session_id: str
    audio_file_id: str
    vad_s3_key: str       # VAD 결과 JSON S3 경로
    speaker_s3_key: str   # 화자 분리 결과 JSON S3 경로
    asr_s3_key: str       # ASR 결과 JSON S3 경로
    options: JobOptions = JobOptions()
