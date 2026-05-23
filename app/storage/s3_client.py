import boto3
from app.config import settings

s3 = boto3.client("s3", region_name=settings.aws_region)


def upload(local_path: str, bucket: str, key: str) -> None:
    s3.upload_file(local_path, bucket, key)


def download(bucket: str, key: str, local_path: str) -> None:
    s3.download_file(bucket, key, local_path)
