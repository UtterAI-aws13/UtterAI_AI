# Clinical Context Agent. tool 없음 — 모든 입력은 LOAD_CONTEXT가 준비한다 (§8.2).
# 참고: 01_production_5_agent_agentic_rag_design.md §8
from __future__ import annotations

from loguru import logger
from strands import Agent
from strands.models import BedrockModel

from app.agents.report_generation.clinical_context.prompt import CLINICAL_CONTEXT_SYSTEM_PROMPT
from app.agents.report_generation.clinical_context.schemas import ClinicalContextOutput
from app.agents.report_generation.config import report_generation_settings as cfg
from app.agents.report_generation.metric_trends import compute_trend_direction
from app.agents.report_generation.models.common import CurrentSession, PatientHistory

# 반응 지연은 낮을수록 좋은 지표라 추세 방향을 뒤집는다.
_LOWER_IS_BETTER_METRICS = {"response_latency_avg_ms"}


def build_clinical_context_agent() -> Agent:
    model = BedrockModel(
        model_id=cfg.context_agent_model_id,
        region_name="ap-northeast-2",
        temperature=cfg.context_agent_temperature,
        max_tokens=4096,
    )
    return Agent(model=model, system_prompt=CLINICAL_CONTEXT_SYSTEM_PROMPT)


def _compute_trend_facts(
    current_session: CurrentSession, patient_history: PatientHistory
) -> dict[str, str]:
    """지표별 trend_direction을 결정론적으로 미리 계산해 Agent에게 사실로 준다."""
    facts: dict[str, str] = {}
    current_metrics = current_session.metrics.model_dump()
    for metric, values in patient_history.metric_trends.items():
        current_value = current_metrics.get(metric)
        series = [*values, current_value] if current_value is not None else values
        facts[metric] = compute_trend_direction(
            [float(v) for v in series if v is not None],
            higher_is_better=metric not in _LOWER_IS_BETTER_METRICS,
        )
    return facts


def analyze_clinical_context(
    current_session: CurrentSession,
    patient_history: PatientHistory,
    max_retries: int = 1,
) -> ClinicalContextOutput:
    """실패 시 한 번 재시도하고, 그래도 실패하면 예외를 낸다 (§8.6).

    호출자(Phase 4 Graph 노드)가 이 예외를 FAILED_CONTEXT_ANALYSIS로 변환한다.
    """
    trend_facts = _compute_trend_facts(current_session, patient_history)

    message = (
        f"[선택 분석 항목]\n{current_session.selected_analysis}\n\n"
        f"[현재 세션 지표]\n{current_session.metrics.model_dump_json(indent=2)}\n\n"
        f"[환자 히스토리]\n{patient_history.model_dump_json(indent=2)}\n\n"
        f"[지표 추세 - 이미 계산됨, 그대로 사용]\n{trend_facts}\n\n"
        f"[세션 조건]\n{current_session.session_conditions}\n\n"
        "위 정보를 바탕으로 핵심 clinical finding을 구조화하라."
    )

    agent = build_clinical_context_agent()
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            result = agent(
                message,
                structured_output_model=ClinicalContextOutput,
                limits={"turns": cfg.context_agent_max_turns},
            )
            if result.structured_output is not None:
                return result.structured_output
            last_error = ValueError("structured_output이 비어 있음")
        except Exception as exc:  # noqa: BLE001 - 재시도 후 상위에서 FailureCode로 변환
            last_error = exc
        logger.warning(f"[clinical_context_agent] 시도 {attempt + 1} 실패: {last_error}")

    raise last_error or RuntimeError("clinical context analysis failed")
