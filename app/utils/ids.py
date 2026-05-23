# ID 생성 유틸리티
# 날짜 기반 job_id, 순번 기반 utterance_id, UUID 기반 report_id를 생성한다
import uuid
from datetime import datetime


def generate_job_id() -> str:
    """날짜 + UUID 앞 8자리 조합으로 중복 없는 job_id를 생성한다.
    예: job_20260523_a3f1c9b2
    """
    date_str = datetime.now().strftime("%Y%m%d")
    return f"job_{date_str}_{uuid.uuid4().hex[:8]}"


def generate_utterance_id(index: int) -> str:
    """발화 순번을 4자리 0-패딩으로 포맷한 utterance_id를 생성한다.
    예: utt_0007
    """
    return f"utt_{index:04d}"


def generate_report_id() -> str:
    """UUID 앞 12자리를 사용한 report_id를 생성한다.
    예: report_a3f1c9b2d4e5
    """
    return f"report_{uuid.uuid4().hex[:12]}"
