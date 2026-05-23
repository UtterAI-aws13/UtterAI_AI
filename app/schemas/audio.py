# 음성 파일 전처리 결과 메타데이터 스키마
# 원본 파일을 16kHz mono WAV로 변환한 뒤 이 스키마로 결과를 기록한다
from pydantic import BaseModel


class AudioMetadata(BaseModel):
    """ffmpeg 전처리 완료 후 생성되는 오디오 파일 메타데이터.

    original_s3_key: 원본 파일 S3 경로
    processed_s3_key: 16kHz mono WAV 변환 파일 S3 경로
    모든 AI 모델은 processed_s3_key의 파일을 입력으로 사용한다.
    """
    original_s3_key: str
    processed_s3_key: str
    duration_sec: float      # 파일 길이 (너무 짧거나 긴 파일 검사에 사용)
    sample_rate: int         # 변환 후 항상 16000
    channels: int            # 변환 후 항상 1 (mono)
    format: str              # 변환 후 항상 "wav"
