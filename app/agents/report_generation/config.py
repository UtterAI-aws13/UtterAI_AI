# Agent별 모델/temperature/retry-budget/QA threshold 설정.
# 참고: 01_production_5_agent_agentic_rag_design.md §15, §27
from pydantic_settings import BaseSettings


class ReportGenerationSettings(BaseSettings):
    graph_version: str = "v1"
    prompt_version: str = "v1"
    schema_version: str = "v1"

    # 프로젝트 기본 리포트 생성 모델(app.config.settings.bedrock_report_model_id)과
    # 동일한 값을 기본값으로 쓰되, Agent별로 독립 override 가능하게 한다.
    context_agent_model_id: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    research_agent_model_id: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    critic_agent_model_id: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    report_agent_model_id: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    qa_agent_model_id: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

    context_agent_temperature: float = 0.1
    research_agent_temperature: float = 0.2
    critic_agent_temperature: float = 0.0
    report_agent_temperature: float = 0.2
    qa_agent_temperature: float = 0.0

    max_research_rounds: int = 3
    max_report_revisions: int = 2
    max_qa_routes: int = 3
    max_total_model_calls: int = 20

    # Agent 호출 1회당 최대 turn 수 (strands Agent의 limits={"turns": N}).
    # 이 상한이 없으면 structured output이 스키마 검증에 계속 실패할 때 Strands가
    # 내부적으로 무한(또는 매우 큰) 재시도를 해 비용이 통제 없이 쌓일 수 있다
    # (로컬 데모에서 EvidenceCriticOutput 생성이 148회 연속 실패한 채 안 끝난 사례로 확인).
    # tool을 쓰는 Agent(Research/Critic)는 정상 작업만으로도 turn 수가 많이 나오므로
    # tool이 없는 Agent보다 넉넉하게 잡는다.
    context_agent_max_turns: int = 6
    research_agent_max_turns: int = 40
    # 근거 후보가 많을 때 fetch_document_section/verify_source_metadata 호출이
    # 늘어나 30으로는 부족한 사례를 실전에서 확인해 50으로 상향했다.
    critic_agent_max_turns: int = 50
    report_agent_max_turns: int = 6
    qa_agent_max_turns: int = 6

    qa_groundedness_threshold: float = 0.90
    qa_citation_threshold: float = 0.95
    qa_context_fidelity_threshold: float = 0.95
    qa_longitudinal_threshold: float = 0.95
    qa_soap_threshold: float = 0.90
    qa_overall_threshold: float = 0.92

    enable_bedrock_guardrails: bool = False
    bedrock_guardrail_id: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


report_generation_settings = ReportGenerationSettings()
