"""5개 Agent의 tool allowlist + structured output 계약. 참고: §25.2.

실제 Bedrock을 호출하지 않는다 - Agent 인스턴스를 mock으로 대체해
tool 구성과 재시도/빈 출력 처리 로직만 검증한다.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.agents.report_generation.clinical_context.schemas import ClinicalContextOutput
from app.agents.report_generation.models.common import CurrentSession, CurrentSessionMetrics, PatientHistory
from app.agents.report_generation.models.report import MetricFinding


def _current_session() -> CurrentSession:
    return CurrentSession(
        session_id="s1", selected_analysis=["MLU"], transcript="x",
        metrics=CurrentSessionMetrics(MLU=3.0),
    )


def _patient_history() -> PatientHistory:
    return PatientHistory(recent_session_count=5, metric_trends={"MLU": [2.1, 2.3, 2.5]})


class TestClinicalContextAgentContract:
    def test_no_tools_allowed(self):
        """§8.2: tool 없음 또는 read-only helper만 - 지금은 tool이 아예 없어야 한다."""
        from app.agents.report_generation.clinical_context.agent import build_clinical_context_agent

        with patch("app.agents.report_generation.clinical_context.agent.Agent") as MockAgent:
            build_clinical_context_agent()
        _, kwargs = MockAgent.call_args
        assert "tools" not in kwargs

    def test_valid_structured_output_returned_on_first_try(self):
        from app.agents.report_generation.clinical_context.agent import analyze_clinical_context

        expected = ClinicalContextOutput(
            primary_findings=[
                MetricFinding(metric="MLU", current_value=3.0, trend_direction="IMPROVING",
                              observation="x", priority="HIGH", confidence=0.9)
            ]
        )
        mock_agent = MagicMock()
        mock_agent.return_value = MagicMock(structured_output=expected)

        with patch(
            "app.agents.report_generation.clinical_context.agent.build_clinical_context_agent",
            return_value=mock_agent,
        ):
            result = analyze_clinical_context(_current_session(), _patient_history())

        assert result == expected
        assert mock_agent.call_count == 1

    def test_caps_turns_to_avoid_unbounded_retry(self):
        """실전에서 관측된 버그의 회귀 방지: structured output이 계속 검증에
        실패하면 Strands가 내부적으로 무한/과다 재시도할 수 있어 turns 상한이
        반드시 걸려 있어야 한다."""
        from app.agents.report_generation.clinical_context.agent import analyze_clinical_context
        from app.agents.report_generation.config import report_generation_settings as cfg

        mock_agent = MagicMock()
        mock_agent.return_value = MagicMock(
            structured_output=ClinicalContextOutput(primary_findings=[])
        )

        with patch(
            "app.agents.report_generation.clinical_context.agent.build_clinical_context_agent",
            return_value=mock_agent,
        ):
            analyze_clinical_context(_current_session(), _patient_history())

        _, kwargs = mock_agent.call_args
        assert kwargs.get("limits") == {"turns": cfg.context_agent_max_turns}

    def test_retries_once_on_empty_output_then_succeeds(self):
        """§8.6: 실패 시 한 번 재시도하고 다시 실패하면 예외."""
        from app.agents.report_generation.clinical_context.agent import analyze_clinical_context

        expected = ClinicalContextOutput(primary_findings=[])
        mock_agent = MagicMock()
        mock_agent.side_effect = [
            MagicMock(structured_output=None),
            MagicMock(structured_output=expected),
        ]

        with patch(
            "app.agents.report_generation.clinical_context.agent.build_clinical_context_agent",
            return_value=mock_agent,
        ):
            result = analyze_clinical_context(_current_session(), _patient_history(), max_retries=1)

        assert result == expected
        assert mock_agent.call_count == 2

    def test_raises_after_exhausting_retries(self):
        from app.agents.report_generation.clinical_context.agent import analyze_clinical_context

        mock_agent = MagicMock()
        mock_agent.return_value = MagicMock(structured_output=None)

        with patch(
            "app.agents.report_generation.clinical_context.agent.build_clinical_context_agent",
            return_value=mock_agent,
        ):
            with pytest.raises(ValueError):
                analyze_clinical_context(_current_session(), _patient_history(), max_retries=1)

        assert mock_agent.call_count == 2  # 최초 시도 + 1회 재시도


class TestEvidenceResearchAgentContract:
    def test_tool_allowlist_matches_spec(self):
        """§9.3: 7개 read-only 검색/보조 tool만 허용된다."""
        from app.agents.report_generation.evidence_research.agent import _AGENT_TOOLS

        tool_names = {t.tool_name for t in _AGENT_TOOLS}
        assert tool_names == {
            "search_korean_evidence",
            "search_international_evidence",
            "search_clinical_guidelines",
            "hybrid_search",
            "rerank_evidence",
            "fetch_document_section",
            "resolve_ontology_synonyms",
        }


class TestEvidenceCriticAgentContract:
    def test_has_no_search_tools(self):
        """§10.2: 검색 tool은 기본적으로 허용하지 않는다."""
        from app.agents.report_generation.evidence_critic.agent import _AGENT_TOOLS

        tool_names = {t.tool_name for t in _AGENT_TOOLS}
        assert tool_names == {"fetch_document_section", "verify_source_metadata", "deduplicate_sources"}
        assert "search_korean_evidence" not in tool_names
        assert "hybrid_search" not in tool_names

    def test_is_distinct_agent_instance_from_research_agent(self):
        """§10.1: Research Agent와 Critic Agent는 반드시 서로 다른 Agent 객체다."""
        from app.agents.report_generation.evidence_critic.agent import build_evidence_critic_agent
        from app.agents.report_generation.evidence_research.agent import build_evidence_research_agent

        research_agent = build_evidence_research_agent()
        critic_agent = build_evidence_critic_agent()
        assert research_agent is not critic_agent


class TestClinicalReportAgentContract:
    def test_no_tools_allowed(self):
        """§11.2: 검색, DB 조회, 저장 tool을 부여하지 않는다."""
        from app.agents.report_generation.clinical_report.agent import build_clinical_report_agent

        with patch("app.agents.report_generation.clinical_report.agent.Agent") as MockAgent:
            build_clinical_report_agent()
        _, kwargs = MockAgent.call_args
        assert "tools" not in kwargs


class TestQualityAssuranceAgentContract:
    def test_no_tools_allowed(self):
        from app.agents.report_generation.quality_assurance.agent import build_quality_assurance_agent

        with patch("app.agents.report_generation.quality_assurance.agent.Agent") as MockAgent:
            build_quality_assurance_agent()
        _, kwargs = MockAgent.call_args
        assert "tools" not in kwargs

    def test_pass_gate_downgrades_llm_pass_when_thresholds_not_met(self):
        """실전에서 실제로 관측된 동작: LLM이 PASS라 해도 safety!=1.0이면 REWRITE로 강등."""
        from app.agents.report_generation.quality_assurance.agent import _enforce_pass_gate
        from app.agents.report_generation.quality_assurance.schemas import QualityAssuranceOutput
        from app.agents.report_generation.models.quality import QualityScores

        output = QualityAssuranceOutput(
            decision="PASS",
            scores=QualityScores(
                groundedness=0.95, citation_correctness=0.98, patient_context_fidelity=0.97,
                longitudinal_consistency=0.97, soap_compliance=0.95, safety=0.9, overall=0.95,
            ),
            route_reason="looks fine",
        )
        result = _enforce_pass_gate(output)
        assert result.decision == "REWRITE"

    def test_pass_gate_keeps_pass_when_all_thresholds_met(self):
        from app.agents.report_generation.quality_assurance.agent import _enforce_pass_gate
        from app.agents.report_generation.quality_assurance.schemas import QualityAssuranceOutput
        from app.agents.report_generation.models.quality import QualityScores

        output = QualityAssuranceOutput(
            decision="PASS",
            scores=QualityScores(
                groundedness=0.95, citation_correctness=0.98, patient_context_fidelity=0.97,
                longitudinal_consistency=0.97, soap_compliance=0.95, safety=1.0, overall=0.95,
            ),
            route_reason="all good",
        )
        result = _enforce_pass_gate(output)
        assert result.decision == "PASS"

    def test_pass_gate_downgrades_on_critical_issue_even_if_scores_pass(self):
        from app.agents.report_generation.quality_assurance.agent import _enforce_pass_gate
        from app.agents.report_generation.quality_assurance.schemas import QualityAssuranceOutput
        from app.agents.report_generation.models.quality import QualityIssue, QualityScores

        output = QualityAssuranceOutput(
            decision="PASS",
            scores=QualityScores(
                groundedness=0.99, citation_correctness=0.99, patient_context_fidelity=0.99,
                longitudinal_consistency=0.99, soap_compliance=0.99, safety=1.0, overall=0.99,
            ),
            issues=[
                QualityIssue(
                    issue_id="i1", category="SAFETY", severity="CRITICAL", section="A",
                    explanation="x", correction_instruction="y",
                )
            ],
            route_reason="looks fine",
        )
        result = _enforce_pass_gate(output)
        assert result.decision == "REWRITE"


def _good_report_for_turns_test():
    from app.agents.report_generation.clinical_report.schemas import ClinicalReportOutput
    from app.agents.report_generation.models.report import SoapDraft, SoapReasoningPlan

    return ClinicalReportOutput(
        reasoning_plan=SoapReasoningPlan(S=[], O=[], A=[], P=[]),
        soap=SoapDraft(S="s", O="o", A="a", P="p"),
        claims=[],
    )


class TestAllAgentsCapTurnsToAvoidUnboundedRetry:
    """실전 버그 회귀 방지: 5개 Agent 전부 limits={"turns": N}을 걸어야 한다.

    이게 없으면 structured output이 스키마 검증에 계속 실패할 때 Strands가
    내부적으로 과다 재시도해 비용이 통제 없이 쌓일 수 있다 (로컬 데모에서
    EvidenceCriticOutput 생성이 148회 연속 실패한 채 멈추지 않은 사례로 확인됨).
    """

    def test_evidence_research_agent(self):
        from app.agents.report_generation.clinical_context.schemas import ClinicalContextOutput
        from app.agents.report_generation.config import report_generation_settings as cfg
        from app.agents.report_generation.evidence_research.agent import research_evidence
        from app.agents.report_generation.evidence_research.schemas import EvidenceResearchOutput

        mock_agent = MagicMock()
        mock_agent.return_value = MagicMock(
            structured_output=EvidenceResearchOutput(requirements=[], queries=[], candidates=[])
        )
        with patch(
            "app.agents.report_generation.evidence_research.agent.build_evidence_research_agent",
            return_value=mock_agent,
        ):
            research_evidence(ClinicalContextOutput(primary_findings=[]))

        _, kwargs = mock_agent.call_args
        assert kwargs.get("limits") == {"turns": cfg.research_agent_max_turns}

    def test_evidence_critic_agent(self):
        from app.agents.report_generation.config import report_generation_settings as cfg
        from app.agents.report_generation.evidence_critic.agent import critique_evidence
        from app.agents.report_generation.evidence_critic.schemas import EvidenceCriticOutput
        from app.agents.report_generation.evidence_research.schemas import EvidenceResearchOutput

        mock_agent = MagicMock()
        mock_agent.return_value = MagicMock(structured_output=EvidenceCriticOutput(decision="ACCEPT"))
        with patch(
            "app.agents.report_generation.evidence_critic.agent.build_evidence_critic_agent",
            return_value=mock_agent,
        ):
            critique_evidence(EvidenceResearchOutput(requirements=[], queries=[], candidates=[]))

        _, kwargs = mock_agent.call_args
        assert kwargs.get("limits") == {"turns": cfg.critic_agent_max_turns}

    def test_clinical_report_agent(self):
        from app.agents.report_generation.clinical_context.schemas import ClinicalContextOutput
        from app.agents.report_generation.clinical_report.agent import write_report
        from app.agents.report_generation.config import report_generation_settings as cfg
        from app.agents.report_generation.evidence_critic.schemas import EvidenceCriticOutput

        mock_agent = MagicMock()
        mock_agent.return_value = MagicMock(structured_output=_good_report_for_turns_test())
        with patch(
            "app.agents.report_generation.clinical_report.agent.build_clinical_report_agent",
            return_value=mock_agent,
        ):
            write_report(
                ClinicalContextOutput(primary_findings=[]), _current_session(), _patient_history(),
                EvidenceCriticOutput(decision="ACCEPT"),
            )

        _, kwargs = mock_agent.call_args
        assert kwargs.get("limits") == {"turns": cfg.report_agent_max_turns}

    def test_quality_assurance_agent(self):
        from app.agents.report_generation.clinical_context.schemas import ClinicalContextOutput
        from app.agents.report_generation.config import report_generation_settings as cfg
        from app.agents.report_generation.evidence_critic.schemas import EvidenceCriticOutput
        from app.agents.report_generation.models.quality import QualityScores
        from app.agents.report_generation.quality_assurance.agent import assess_quality
        from app.agents.report_generation.quality_assurance.schemas import QualityAssuranceOutput

        mock_agent = MagicMock()
        mock_agent.return_value = MagicMock(
            structured_output=QualityAssuranceOutput(
                decision="PASS",
                scores=QualityScores(groundedness=1, citation_correctness=1, patient_context_fidelity=1,
                                      longitudinal_consistency=1, soap_compliance=1, safety=1, overall=1),
                route_reason="x",
            )
        )
        with patch(
            "app.agents.report_generation.quality_assurance.agent.build_quality_assurance_agent",
            return_value=mock_agent,
        ):
            assess_quality(
                ClinicalContextOutput(primary_findings=[]), _current_session(), _patient_history(),
                EvidenceCriticOutput(decision="ACCEPT"), _good_report_for_turns_test(),
            )

        _, kwargs = mock_agent.call_args
        assert kwargs.get("limits") == {"turns": cfg.qa_agent_max_turns}
