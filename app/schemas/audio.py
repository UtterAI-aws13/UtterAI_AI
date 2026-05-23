from pydantic import BaseModel


class AudioMetadata(BaseModel):
    original_s3_key: str
    processed_s3_key: str
    duration_sec: float
    sample_rate: int
    channels: int
    format: str
