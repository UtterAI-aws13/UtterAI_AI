# 리포트 생성 파이프라인
# 언어 지표 + RAG 검색 근거를 EXAONE에 입력해 SOAP Note 초안 JSON을 생성한다
# JSON 파싱 실패 시 retry / schema repair 로직이 필요하다
import json
from app.schemas import Utterance, SpeakerMetrics, RagResult, ReportDraft
from app.rag.prompt_templates import build_report_prompt


def generate_report(
    job_id: str,
    session_id: str,
    utterances: list[Utterance],
    metrics: list[SpeakerMetrics],
    rag_result: RagResult,
    llm,
) -> ReportDraft:
    """EXAONE에 프롬프트를 전달하고 반환된 JSON을 ReportDraft로 변환한다.

    프롬프트는 build_report_prompt()가 빌드하며,
    지표 수치, 대표 발화(최대 10개), RAG 근거 chunk를 포함한다.
    출력 JSON이 ReportDraft schema를 만족하지 않으면 재시도한다.
    """
    prompt = build_report_prompt(utterances, metrics, rag_result)
    raw = llm.predict(prompt)
    # TODO: JSON 파싱 실패 시 retry / schema repair
    data = json.loads(raw)
    raise NotImplementedError
