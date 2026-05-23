# 음성 파일 유틸리티
# 파일 길이 측정과 기본 유효성 검사를 담당한다
# preprocess_audio 파이프라인에서 호출한다


def get_audio_duration(audio_path: str) -> float:
    """soundfile 또는 librosa로 음성 파일의 길이(초)를 반환한다."""
    # TODO: soundfile 또는 librosa로 duration 측정
    raise NotImplementedError


def validate_audio(audio_path: str) -> None:
    """포맷 체크와 길이 검사를 수행한다. 문제가 있으면 예외를 발생시킨다.

    검사 항목:
    - 지원 포맷 여부 (wav, mp3, m4a 등)
    - 너무 짧은 파일 (VAD_NO_SPEECH 오류 방지)
    - 너무 긴 파일 (Worker 처리 시간 초과 방지)
    """
    # TODO: 포맷 체크, 너무 짧거나 긴 파일 검사
    raise NotImplementedError
