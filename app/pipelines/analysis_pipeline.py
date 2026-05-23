# 전체 분석 파이프라인 오케스트레이터
# Worker가 SQS 메시지를 수신하면 이 함수를 호출해 전체 파이프라인을 순서대로 실행한다
# 각 단계 진입 시 Job 상태를 DB에 업데이트하고, 실패 시 JobFailureInfo를 저장한다
from app.schemas import JobMessage
from app.pipelines.audio_preprocess import preprocess_audio
from app.pipelines.alignment import align_segments
from app.pipelines.metrics_pipeline import calculate_metrics
from app.pipelines.report_pipeline import generate_report


def run_analysis(message: JobMessage) -> None:
    """JobMessage를 받아 전체 AI 분석 파이프라인을 실행한다.

    실행 순서:
    1. S3에서 음성 다운로드
    2. ffmpeg 전처리 (16kHz mono WAV)
    3. Silero VAD (말소리 구간 추출)
    4. pyannote 화자 분리
    5. Whisper STT
    6. VAD + 화자 + STT 정렬 → Utterance 생성
    7. Kiwi 형태소 분석 → morphemes 채우기
    8. 언어 지표 계산 (MLU, NDW, NTW, TTR, latency)
    9. RAG 문서 검색
    10. EXAONE 리포트 초안 생성
    11. S3/RDS 저장
    """
    # TODO: 각 단계별 job status 업데이트 + 결과 저장
    raise NotImplementedError
