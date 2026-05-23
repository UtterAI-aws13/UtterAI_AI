from app.schemas import JobMessage
from app.pipelines.audio_preprocess import preprocess_audio
from app.pipelines.alignment import align_segments
from app.pipelines.metrics_pipeline import calculate_metrics
from app.pipelines.report_pipeline import generate_report


def run_analysis(message: JobMessage) -> None:
    # TODO: 각 단계별 job status 업데이트 + 결과 저장
    raise NotImplementedError
