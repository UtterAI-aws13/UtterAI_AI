# S3 클라이언트 래퍼
# 음성 파일, 전사 결과 JSON, 리포트 JSON, RAG 원본 문서를 S3에 저장/조회한다
# 버킷별 역할: utterai-audio(음성), utterai-report(리포트), utterai-rag(RAG 문서)
import boto3
from app.config import settings

s3 = boto3.client("s3", region_name=settings.aws_region)


def upload(local_path: str, bucket: str, key: str) -> None:
    """로컬 파일을 S3에 업로드한다."""
    s3.upload_file(local_path, bucket, key)


def download(bucket: str, key: str, local_path: str) -> None:
    """S3 파일을 로컬에 다운로드한다."""
    s3.download_file(bucket, key, local_path)


def get_bytes(bucket: str, key: str) -> bytes:
    """S3 오브젝트를 bytes로 직접 읽는다."""
    response = s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()
