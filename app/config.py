# 환경 변수 기반 설정 관리
# pydantic-settings를 사용해 .env 파일 또는 환경 변수에서 자동으로 로드한다
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """서비스 전체 설정. 모든 값은 .env 파일 또는 환경 변수로 주입한다.

    모델 관련 설정은 각 모델 Wrapper 초기화 시 settings에서 꺼내서 사용한다.
    """
    app_env: str = "local"     # local / dev / prod
    log_level: str = "INFO"

    # Hugging Face - pyannote 모델 접근 권한에 필요
    hf_token: str = ""

    # AWS
    aws_region: str = "ap-northeast-2"
    s3_bucket_audio: str = "utterai-dev-raw-audio"
    s3_bucket_report: str = "utterai-dev-reports"
    s3_bucket_rag: str = "utterai-dev-rag-ingest"
    s3_bucket_transcript: str = "utterai-dev-transcripts"

    # AI DB - pgvector 확장 포함된 PostgreSQL (RAG 벡터 검색용)
    db_user: str = ""
    db_password: str = ""
    db_host: str = ""
    db_port: int = 5432
    db_name: str = ""

    @property
    def database_url(self):
        from sqlalchemy import URL
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )

    # BE RDS - analysis_jobs / transcripts / transcript_segments 테이블 (ML GPU Worker만 사용)
    be_db_user: str = ""
    be_db_password: str = ""
    be_db_host: str = ""
    be_db_port: int = 5432
    be_db_name: str = ""

    @property
    def be_database_url(self):
        from sqlalchemy import URL
        return URL.create(
            "postgresql+psycopg",
            username=self.be_db_user,
            password=self.be_db_password,
            host=self.be_db_host,
            port=self.be_db_port,
            database=self.be_db_name,
        )


    # Worker 타입 - Pod 환경변수로 주입 (cpu / ml-gpu / llm-gpu)
    worker_type: str = "cpu"

    # SQS
    sqs_audio_preprocess_queue_url: str = ""
    sqs_gpu_inference_queue_url: str = ""
    sqs_report_analysis_queue_url: str = ""
    sqs_rag_ingest_queue_url: str = ""

    # Bedrock
    bedrock_region: str = "ap-northeast-2"
    bedrock_report_model_id: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

    # AgentCore — AWS 콘솔에서 생성한 Agent ID와 Alias ID를 환경 변수로 주입
    agentcore_agent_id: str = ""
    agentcore_agent_alias_id: str = "PROD"

    # 모델 이름 - Hugging Face Hub ID
    vad_model_name: str = "onnx-community/silero-vad"
    diarization_model_name: str = "pyannote/speaker-diarization-3.1"
    asr_model_name: str = "large-v3-turbo"
    embedding_model_name: str = "nlpai-lab/KURE-v1"

    # 디바이스 - CPU Worker와 GPU Worker를 분리 배포할 때 각각 다르게 설정
    asr_device: str = "cuda"
    diarization_device: str = "cuda"


    # RAG 검색 파라미터
    rag_top_k: int = 5               # 검색 결과 상위 k개
    rag_score_threshold: float = 0.5  # 이 점수 미만의 chunk는 근거에서 제외

    # OpenTelemetry
    otel_service_name: str = "ai"
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    otel_exporter_otlp_protocol: str = "http/protobuf"
    otel_metrics_exporter: str = "otlp"
    otel_traces_exporter: str = "otlp"
    otel_logs_exporter: str = "none"
    otel_resource_attributes: str = "deployment.environment=local,team=utterai"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
