from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "local"
    log_level: str = "INFO"

    hf_token: str = ""

    aws_region: str = "ap-northeast-2"
    s3_bucket_audio: str = "utterai-audio-dev"
    s3_bucket_report: str = "utterai-report-dev"
    s3_bucket_rag: str = "utterai-rag-dev"

    database_url: str = ""

    sqs_analysis_queue_url: str = ""
    sqs_rag_ingest_queue_url: str = ""

    vad_model_name: str = "onnx-community/silero-vad"
    diarization_model_name: str = "pyannote/speaker-diarization-3.1"
    asr_model_name: str = "openai/whisper-large-v3-turbo"
    embedding_model_name: str = "nlpai-lab/KURE-v1"
    llm_model_name: str = "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct"

    model_device: str = "auto"
    asr_device: str = "cuda"
    diarization_device: str = "cuda"
    llm_device: str = "cuda"

    rag_top_k: int = 5
    rag_score_threshold: float = 0.5

    model_config = {"env_file": ".env"}


settings = Settings()
