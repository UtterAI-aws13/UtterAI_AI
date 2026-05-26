# 음성 파일 유틸리티
# 파일 길이 측정과 기본 유효성 검사를 담당한다
# preprocess_audio 파이프라인에서 호출한다


from pathlib import Path

SUPPORTED_SUFFIXES = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}
MIN_DURATION_SEC = 3.0
MAX_DURATION_SEC = 3600.0


def get_audio_duration(audio_path: str) -> float:
    """soundfile → librosa 순으로 시도해 음성 파일 길이(초)를 반환한다."""
    try:
        import soundfile as sf
        return sf.info(audio_path).duration
    except Exception:
        pass

    try:
        import librosa
        return librosa.get_duration(path=audio_path)
    except Exception:
        pass

    raise RuntimeError(f"오디오 길이 측정 실패: {audio_path}")


def validate_audio(audio_path: str) -> None:
    """포맷 체크와 길이 검사. 문제가 있으면 ValueError를 발생시킨다."""
    path = Path(audio_path)

    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"지원하지 않는 포맷: {path.suffix} (지원: {sorted(SUPPORTED_SUFFIXES)})"
        )

    duration = get_audio_duration(audio_path)

    if duration < MIN_DURATION_SEC:
        raise ValueError(
            f"파일이 너무 짧음: {duration:.1f}s (최소 {MIN_DURATION_SEC}s)"
        )

    if duration > MAX_DURATION_SEC:
        raise ValueError(
            f"파일이 너무 김: {duration:.1f}s (최대 {MAX_DURATION_SEC / 3600:.0f}시간)"
        )
