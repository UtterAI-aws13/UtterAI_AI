"""
Arize Phoenix Experiment: E2E 리포트 생성 legacy baseline 평가.

utterai_phoenix_e2e_dataset_v1 (GUI 업로드, 8케이스)을 이용해 legacy
"retrieve_evidence -> build_template_report_prompt -> Bedrock Claude" 경로
(app.pipelines.report_pipeline이 template_sections가 있을 때 타는 경로,
정확히 dataset metadata의 baseline_path와 동일)로 실제 SOAP형 리포트를
생성하고 평가한다.

신규 5-agent 경로(run_report_generation())는 이번 스코프에서 보류한다 -
실제 session_id/patient_ref_id/therapist_id로 DB 레포지토리를 읽어야 해서
raw JSON 입력을 바로 못 받는다. prod DB에 테스트용 row를 쓰는 것도 하지
않기로 했다. 로컬 DB에 fixture를 심어 5-agent를 도는 방법은 별도로 논의한다.

데이터셋 example 스키마:
  inputs: {question, metrics: {mlu, ttr, ndw, latency_seconds, utterance_count},
           utterances: [{speaker, text, start_sec?, end_sec?}, ...],
           session: {session_id, patient_group, age_band, session_type,
                     duration_minutes, primary_goal, sampling_context, ...},
           sections: [{key, title, description}, ...]}
  reference: {answer, expected_document_ids, expected_behavior}
  metadata: {case_id, category, difficulty, dataset_type, baseline_path, dataset_version}

Evaluator:
  - hit_at_k / recall_at_k        (코드) expected_document_ids 검색 적중
  - section_structure_compliance  (코드) 요청한 모든 section key가 비어있지 않게 채워졌는가
  - document_relevance            (LLM judge) 검색된 chunk가 질문과 관련 있는가
  - faithfulness                  (LLM judge) 생성된 리포트가 근거에 충실한가
  - clinical_answer_quality       (LLM judge, custom) reference answer + expected_behavior 대비

실행:
  APP_ENV=dev DB_HOST=... PHOENIX_BASE_URL=http://localhost:6006 \
    python scripts/eval_phoenix_e2e_experiment.py
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

load_dotenv()

from phoenix.client import Client
from phoenix.client.resources.datasets import Dataset

DATASET_NAME = "utterai_phoenix_e2e_dataset_v1"
TOP_K = 5
_JUDGE_MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

_RESTRICTIVE_BEHAVIORS = {"reject_overdiagnosis"}

# scripts/eval_phoenix_experiment.py와 동일한 이유로 실제 prod corpus 기준 보정한다.
# doc_latency/doc_soap_template은 대응하는 실제 문서가 없어 그대로 둔다 - 해당
# 케이스(E2E-LAT-001, E2E-SOAP-001)는 hit_at_k/recall이 낮게 나오는 게 정상이며
# document_relevance/faithfulness/clinical_answer_quality로 평가 가치는 유지된다.
_DOC_ID_CORRECTIONS = {
    "doc_mlu_guide": ["doc_metric_mlu_korean_rule", "doc_language_sample_analysis", "doc_language_sample_metrics"],
    "doc_ttr_ndw": ["doc_language_sample_metrics"],
}


def _corrected_dataset(client: Client, name: str) -> Dataset:
    dataset = client.datasets.get_dataset(dataset=name)
    examples = []
    for example in dataset.examples:
        corrected_docs: list[str] = []
        for doc_id in example["output"].get("expected_document_ids", []):
            for corrected in _DOC_ID_CORRECTIONS.get(doc_id, [doc_id]):
                if corrected not in corrected_docs:
                    corrected_docs.append(corrected)
        examples.append(
            {**example, "output": {**example["output"], "expected_document_ids": corrected_docs}}
        )
    examples_data = {**dataset._examples_data, "examples": examples}  # noqa: SLF001
    return Dataset(dataset._dataset_info, examples_data)  # noqa: SLF001


# ── Bedrock 호출 헬퍼 (judge 전용 - invoke_claude()는 리포트 생성 자체에 재사용) ──

def _invoke_bedrock_text(prompt: str, max_tokens: int = 512) -> str:
    from app.pipelines.bedrock_client import get_bedrock_client

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "messages": [{"role": "user", "content": prompt}],
    })
    response = get_bedrock_client().invoke_model(
        modelId=_JUDGE_MODEL_ID, body=body, contentType="application/json", accept="application/json",
    )
    parsed = json.loads(response["body"].read())
    return parsed["content"][0]["text"]


def _invoke_bedrock_json(prompt: str) -> dict:
    text = _invoke_bedrock_text(prompt)
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {"score": 0.0, "explanation": f"judge 응답 파싱 실패: {text[:200]}"}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"score": 0.0, "explanation": f"judge JSON 파싱 실패: {text[:200]}"}


def _map_metrics(raw: dict) -> dict:
    return {
        "mlu_word": raw.get("mlu", 0),
        "ttr": raw.get("ttr", 0),
        "ndw": raw.get("ndw", 0),
        "avg_response_latency_sec": raw.get("latency_seconds", 0),
        "max_response_latency_sec": raw.get("latency_seconds", 0),
        "total_utterances": raw.get("utterance_count", 0),
    }


def _map_utterances(raw: list[dict]) -> list[dict]:
    role_map = {"therapist": "SLP", "patient": "PATIENT"}
    return [
        {"speaker_role": role_map.get(u.get("speaker", ""), u.get("speaker", "UNKNOWN")), "text": u.get("text", "")}
        for u in raw
    ]


# ── Task: legacy template 경로 (report_pipeline.py의 template_sections 분기와 동일) ──

def task_legacy_template_report(input: dict) -> dict:
    import asyncio

    from app.pipelines.bedrock_client import invoke_claude
    from app.rag.prompt_templates import build_template_report_prompt
    from app.rag.retriever import retrieve_evidence

    question = input["question"]
    metrics = _map_metrics(input.get("metrics") or {})
    utterances = _map_utterances(input.get("utterances") or [])
    session = input.get("session") or {}
    sections = input.get("sections") or []

    evidence = asyncio.run(
        retrieve_evidence(metrics={}, session={}, top_k=TOP_K, direct_query=question)
    )
    prompt = build_template_report_prompt(
        metrics=metrics, utterances=utterances, session=session, evidence=evidence, sections=sections
    )
    report_data = invoke_claude(prompt)

    return {
        "chunks": [
            {"document_id": e["document_id"], "chunk_id": e["chunk_id"], "text": e["content"], "score": e["score"]}
            for e in evidence
        ],
        "report_sections": report_data.get("sections", {}),
        "clinical_flags": report_data.get("clinical_flags", []),
        "requested_section_keys": [s.get("key", "") for s in sections],
    }


# ── Evaluator ────────────────────────────────────────────────────────────────

def hit_at_k(output: dict, expected: dict) -> bool:
    retrieved = {c["document_id"] for c in output["chunks"]}
    return bool(retrieved & set(expected["expected_document_ids"]))


def recall_at_k(output: dict, expected: dict) -> float:
    expected_docs = set(expected["expected_document_ids"])
    if not expected_docs:
        return 1.0
    retrieved = {c["document_id"] for c in output["chunks"]}
    return len(retrieved & expected_docs) / len(expected_docs)


def section_structure_compliance(output: dict) -> dict:
    """요청한 모든 section key가 비어있지 않은 내용으로 채워졌는지 확인한다."""
    requested = output["requested_section_keys"]
    sections = output["report_sections"]
    if not requested:
        return {"score": 1.0, "explanation": "요청된 section 없음"}
    filled = [k for k in requested if str(sections.get(k, "")).strip()]
    missing = [k for k in requested if k not in filled]
    return {
        "score": len(filled) / len(requested),
        "explanation": f"누락된 section: {missing}" if missing else "전체 section 채워짐",
    }


def _joined_report_text(output: dict) -> str:
    return "\n\n".join(f"[{k}] {v}" for k, v in output["report_sections"].items())


def document_relevance(input: dict, output: dict) -> dict:
    chunks = output["chunks"]
    if not chunks:
        return {"score": 0.0, "explanation": "검색된 chunk 없음"}
    scores, explanations = [], []
    for c in chunks:
        prompt = (
            f'질문: "{input["question"]}"\n\n문서 발췌: "{c["text"][:500]}"\n\n'
            "이 문서 발췌가 질문에 답하는 데 관련이 있는지 0.0~1.0 사이 점수로 평가하라. "
            'JSON으로만 답하라: {"score": 0.0~1.0, "explanation": "..."}'
        )
        result = _invoke_bedrock_json(prompt)
        scores.append(float(result.get("score", 0.0)))
        explanations.append(f"{c['document_id']}: {result.get('explanation', '')}")
    return {"score": sum(scores) / len(scores), "explanation": " | ".join(explanations)}


def faithfulness(output: dict) -> dict:
    context = "\n\n".join(f"[{c['document_id']}] {c['text']}" for c in output["chunks"])
    report_text = _joined_report_text(output)
    prompt = (
        f"근거 문서:\n{context}\n\n생성된 리포트:\n{report_text}\n\n"
        "이 리포트가 근거 문서의 내용만으로 뒷받침되는지(환각·근거 없는 단정이 없는지) "
        '0.0~1.0 사이 점수로 평가하라. JSON으로만 답하라: '
        '{"score": 0.0~1.0, "explanation": "..."}'
    )
    return _invoke_bedrock_json(prompt)


def clinical_answer_quality(output: dict, expected: dict) -> dict:
    behavior = expected.get("expected_behavior", "")
    behavior_note = (
        "이 케이스는 질문이 과잉진단/단일원인 확정을 요구하므로 리포트가 "
        "**확정을 거부**해야 한다. 리포트가 실제로 진단/원인을 확정해버렸다면 "
        "반드시 낮은 점수를 줘라."
        if behavior in _RESTRICTIVE_BEHAVIORS
        else f"이 케이스의 기대 행동 유형은 '{behavior}'이다 (리포트가 이 성격에 맞게 작성됐는지 확인)."
    )
    report_text = _joined_report_text(output)
    prompt = (
        f"기준 답변: \"{expected['answer']}\"\n"
        f"기대 행동 유형: {behavior}\n{behavior_note}\n\n"
        f"생성된 리포트:\n{report_text}\n\n"
        "생성된 리포트가 기준 답변과 핵심 임상 판단이 부합하고, 기대 행동 유형에 맞게 "
        "작성됐으며, 과장되거나 진단을 단정하는 표현이 없는지 0.0~1.0 사이 점수로 "
        '평가하라. 문구가 똑같을 필요는 없다. JSON으로만 답하라: '
        '{"score": 0.0~1.0, "explanation": "..."}'
    )
    return _invoke_bedrock_json(prompt)


# ── 실행 ──────────────────────────────────────────────────────────────────────

def main():
    base_url = os.environ.get("PHOENIX_BASE_URL", "http://localhost:6006")
    client = Client(base_url=base_url)
    dataset = _corrected_dataset(client, DATASET_NAME)

    evaluators = [
        hit_at_k, recall_at_k, section_structure_compliance,
        document_relevance, faithfulness, clinical_answer_quality,
    ]

    tag = os.environ.get("EVAL_TAG", "unknown")
    print(f"\n=== E2E legacy template report 실행 (dataset={DATASET_NAME}, {tag}) ===")
    client.experiments.run_experiment(
        dataset=dataset,
        task=task_legacy_template_report,
        evaluators=evaluators,
        experiment_name=f"legacy-e2e-template-report-{tag}",
        experiment_description="retrieve_evidence -> build_template_report_prompt -> Bedrock Claude",
    )

    print(f"\nPhoenix UI에서 Datasets > {DATASET_NAME} > Experiments 비교 화면 확인: {base_url}")


if __name__ == "__main__":
    main()
