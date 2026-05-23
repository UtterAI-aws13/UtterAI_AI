import uuid
from datetime import datetime


def generate_job_id() -> str:
    date_str = datetime.now().strftime("%Y%m%d")
    return f"job_{date_str}_{uuid.uuid4().hex[:8]}"


def generate_utterance_id(index: int) -> str:
    return f"utt_{index:04d}"


def generate_report_id() -> str:
    return f"report_{uuid.uuid4().hex[:12]}"
