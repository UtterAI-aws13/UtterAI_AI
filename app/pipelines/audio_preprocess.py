# 음성 전처리 파이프라인
# 원본 파일(mp3, m4a, wav 등)을 모든 AI 모델이 공통으로 사용하는 표준 포맷으로 변환한다
# 표준 포맷: 16kHz, mono, 16-bit PCM WAV
from app.schemas import AudioMetadata


def preprocess_audio(input_path: str, output_path: str) -> AudioMetadata:
    """원본 음성 파일을 16kHz mono WAV로 변환하고 메타데이터를 반환한다.

    ffmpeg를 사용해 포맷 변환, duration 측정, 너무 짧거나 긴 파일 검사를 수행한다.
    변환된 파일은 processed S3 버킷에 저장된다.
    """
    import subprocess
    from pathlib import Path
    from app.utils.audio import get_audio_duration, validate_audio

    validate_audio(input_path)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", input_path,
            "-ar", "16000",
            "-ac", "1",
            "-sample_fmt", "s16",
            output_path,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 변환 실패:\n{result.stderr}")

    duration = get_audio_duration(output_path)

    return AudioMetadata(
        original_s3_key=input_path,
        processed_s3_key=output_path,
        duration_sec=round(duration, 3),
        sample_rate=16000,
        channels=1,
        format="wav",
    )
