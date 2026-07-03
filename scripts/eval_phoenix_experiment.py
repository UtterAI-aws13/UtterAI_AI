"""
Arize Phoenix Experiment: legacy retrieve_evidence() 경로 vs 새 Retriever
(Kiwi 형태소 분석 → ontology.yaml 확장 → 메타데이터 필터 → pgvector → fallback)
경로를 Phoenix GUI로 이미 만든 데이터셋(utterai_phoenix_eval_dataset_v1)으로
각각 독립 실행해 Phoenix UI에서 비교한다.

데이터셋 example 스키마 (GUI 업로드 시 사용한 형태):
  inputs:   {"question": str, "session_metrics": dict}
  reference: {"answer": str, "expected_document_ids": list[str], "expected_behavior": str}
  metadata: {"case_id", "category", "metric", "difficulty", "question_type", ...}

expected_behavior 값: answer_with_caveat, reject_overdiagnosis, reject_single_cause,
  answer_with_method, answer_with_template_guidance, abstain, abstain_and_redirect,
  answer_with_insufficient_population_reference 등 - 생성된 답변이 이 행동 유형에
  맞게 반응했는지를 clinical_answer_quality evaluator가 함께 판단한다.

Evaluator:
  - hit_at_k              (코드) expected_document_ids 중 하나라도 top_k 안에 있는가
  - recall_at_k           (코드) expected_document_ids를 얼마나 찾았는가
  - document_relevance    (LLM judge) 검색된 각 chunk가 질문과 관련 있는가
  - faithfulness          (LLM judge) 생성된 답변이 검색 근거에 충실한가
  - clinical_answer_quality (LLM judge, custom) 생성된 답변을 reference answer +
    expected_behavior와 비교해 임상 문서로서 적절한지(과잉진단 거부/보류가
    필요한 case에서 실제로 그렇게 반응했는지 포함) 평가

실행 전 준비:
  1. Phoenix 서버 접속 가능해야 한다 (PHOENIX_BASE_URL, 기본 http://localhost:6006 -
     EKS의 실제 Phoenix라면 kubectl port-forward 후 그 주소를 지정한다).
  2. uv sync (arize-phoenix-client는 dev dependency-group에 이미 추가됨).

권장 실행 순서 (머지 전/후 비교로 실제 개선 여부를 데이터로 남긴다):
  1. main 브랜치(app.agents.report_generation이 아직 없는 상태)에서
     --task legacy 실행 → "머지 전 baseline" experiment 적재.
  2. 이 PR을 main에 머지.
  3. main에서 다시 --task both 실행 → "머지 후" legacy/new 비교 experiment 적재.
  실행할 때마다 experiment 이름에 <브랜치>@<커밋 SHA>가 자동으로 붙어
  Phoenix UI에서 어느 시점 코드로 나온 결과인지 구분할 수 있다.

실행:
  APP_ENV=local PHOENIX_BASE_URL=http://localhost:6006 python scripts/eval_phoenix_experiment.py --task legacy
  APP_ENV=local PHOENIX_BASE_URL=http://localhost:6006 python scripts/eval_phoenix_experiment.py --task both
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

DATASET_NAME = "utterai_phoenix_eval_dataset_v1"
TOP_K = 5
_JUDGE_MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

_RESTRICTIVE_BEHAVIORS = {
    "reject_overdiagnosis",
    "reject_single_cause",
    "abstain",
    "abstain_and_redirect",
}

# v1 데이터셋 작성 시점엔 없던 실제 corpus 문서 ID로 보정한다 (실제 prod pgvector에
# doc_mlu_guide/doc_ttr_ndw라는 이름의 문서는 없고, 동일 주제를 다루는 문서가 다른
# ID로 존재함 - 2026-07-03 prod DB 대조로 확인). 데이터셋 자체(Phoenix v1)는 건드리지
# 않고 이 스크립트에서 실행 시점에만 보정한다.
_DOC_ID_CORRECTIONS = {
    "doc_mlu_guide": ["doc_metric_mlu_korean_rule", "doc_language_sample_analysis", "doc_language_sample_metrics"],
    "doc_ttr_ndw": ["doc_language_sample_metrics"],
}

# doc_latency/doc_soap_template처럼 corpus에 아예 콘텐츠가 없는 케이스(LAT-*, SOAP-*)는
# retrieval 평가 스코프가 아니다 - v2(end-to-end, utterances/session/sections 포함)
# 데이터셋에서 콘텐츠를 보강해 다시 다룬다. v1 Phoenix 데이터셋 자체는 유지한다.
_EXCLUDED_CASE_ID_PREFIXES = ("LAT-", "SOAP-")


def _retrieval_scoped_dataset(client: Client, name: str) -> Dataset:
    """v1 데이터셋에서 LAT-*/SOAP-* 케이스를 빼고 문서 ID를 실제 corpus 기준으로 보정한
    사본을 만든다. Phoenix에 저장된 원본 데이터셋은 수정하지 않는다."""
    dataset = client.datasets.get_dataset(dataset=name)

    scoped_examples = []
    for example in dataset.examples:
        case_id = example["metadata"].get("case_id", "")
        if case_id.startswith(_EXCLUDED_CASE_ID_PREFIXES):
            continue
        corrected_docs = []
        for doc_id in example["output"].get("expected_document_ids", []):
            for corrected in _DOC_ID_CORRECTIONS.get(doc_id, [doc_id]):
                if corrected not in corrected_docs:
                    corrected_docs.append(corrected)
        scoped_examples.append(
            {**example, "output": {**example["output"], "expected_document_ids": corrected_docs}}
        )

    examples_data = {**dataset._examples_data, "examples": scoped_examples}  # noqa: SLF001
    excluded = dataset.example_count - len(scoped_examples)
    print(f"[dataset scope] {name}: 전체 {dataset.example_count}개 중 {excluded}개 제외(LAT-*/SOAP-*), "
          f"{len(scoped_examples)}개로 실행")
    return Dataset(dataset._dataset_info, examples_data)  # noqa: SLF001


# ── Bedrock 호출 헬퍼 (이 스크립트 전용 - 앱 요청 경로의 invoke_claude()는 JSON 리포트
#    스키마용이라 자유 텍스트 생성/판정에는 맞지 않는다) ──────────────────────────

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


def _generate_answer(question: str, session_metrics: dict, chunks: list[dict]) -> str:
    if not chunks:
        return "근거 문헌을 찾지 못해 답변할 수 없습니다."
    context = "\n\n".join(f"[{c['document_id']}] {c['text']}" for c in chunks)
    metrics_text = f"\n\n세션 지표: {session_metrics}" if session_metrics else ""
    prompt = (
        f"다음은 언어재활 근거 문서 발췌다.\n\n{context}\n\n"
        f"질문: {question}{metrics_text}\n\n"
        "위 근거만 사용해 2~3문장으로 답변하라. 근거에 없는 내용은 말하지 않는다. "
        "진단을 단정하지 않는다. 단일 지표만으로 진단/치료 결정을 확정해 달라는 "
        "요청에는 확정해줄 수 없다는 점을 분명히 밝히고 종합 평가가 필요함을 안내한다."
    )
    return _invoke_bedrock_text(prompt)


# ── Task: 두 검색 경로를 각각 독립 실행 ──────────────────────────────────────
# Phoenix Client(동기)는 async task 함수를 지원하지 않는다("Use the AsyncClient
# instead" - 실제로 돌려서 확인함). asyncio.run()으로 내부에서만 async I/O를 태운다.

def task_legacy_retrieve_evidence(input: dict) -> dict:
    """app.rag.retriever.retrieve_evidence() - Kiwi/ontology/필터 없이 raw 쿼리 임베딩."""
    import asyncio

    from app.rag.retriever import retrieve_evidence

    question = input["question"]
    session_metrics = input.get("session_metrics") or {}
    results = asyncio.run(
        retrieve_evidence(metrics={}, session={}, top_k=TOP_K, direct_query=question)
    )
    chunks = [
        {"document_id": r["document_id"], "chunk_id": r["chunk_id"], "text": r["content"], "score": r["score"]}
        for r in results
    ]
    return {"chunks": chunks, "answer": _generate_answer(question, session_metrics, chunks)}


def task_new_kiwi_ontology_pipeline(input: dict) -> dict:
    """app.agents.report_generation.evidence_research.tools._search() -
    Kiwi 형태소 분석 → ontology 확장 → 메타데이터 필터 → 벡터 검색 → fallback."""
    import asyncio

    from app.agents.report_generation.evidence_research.tools import _search

    question = input["question"]
    session_metrics = input.get("session_metrics") or {}
    results = asyncio.run(_search(question, top_k=TOP_K))
    chunks = [
        {"document_id": r["source_id"], "chunk_id": r["chunk_id"], "text": r["text"], "score": r["retrieval_score"]}
        for r in results
    ]
    return {"chunks": chunks, "answer": _generate_answer(question, session_metrics, chunks)}


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


def document_relevance(input: dict, output: dict) -> dict:
    """LLM judge: 검색된 각 chunk가 질문과 관련 있는지 0~1로 평가해 평균낸다."""
    chunks = output["chunks"]
    if not chunks:
        return {"score": 0.0, "explanation": "검색된 chunk 없음"}

    scores = []
    explanations = []
    for c in chunks:
        prompt = (
            f'질문: "{input["question"]}"\n\n문서 발췌: "{c["text"][:500]}"\n\n'
            "이 문서 발췌가 질문에 답하는 데 관련이 있는지 0.0~1.0 사이 점수로 평가하라. "
            'JSON으로만 답하라: {"score": 0.0~1.0, "explanation": "..."}'
        )
        result = _invoke_bedrock_json(prompt)
        scores.append(float(result.get("score", 0.0)))
        explanations.append(f"{c['document_id']}: {result.get('explanation', '')}")

    return {
        "score": sum(scores) / len(scores),
        "explanation": " | ".join(explanations),
    }


def faithfulness(output: dict) -> dict:
    """LLM judge: 생성된 답변이 검색된 근거에 충실한지(환각 없는지) 평가."""
    context = "\n\n".join(f"[{c['document_id']}] {c['text']}" for c in output["chunks"])
    prompt = (
        f"근거 문서:\n{context}\n\n생성된 답변: \"{output['answer']}\"\n\n"
        "이 답변이 근거 문서의 내용만으로 뒷받침되는지(환각·근거 없는 단정이 없는지) "
        '0.0~1.0 사이 점수로 평가하라. JSON으로만 답하라: '
        '{"score": 0.0~1.0, "explanation": "..."}'
    )
    return _invoke_bedrock_json(prompt)


def clinical_answer_quality(output: dict, expected: dict) -> dict:
    """커스텀 LLM judge: 생성된 답변을 reference answer + expected_behavior와 비교한다.

    표현이 똑같을 필요는 없지만, expected_behavior가 reject_overdiagnosis/
    reject_single_cause/abstain/abstain_and_redirect처럼 "확정/과잉해석을
    거부해야 하는" 케이스인데 생성된 답변이 실제로 진단·원인을 확정해버리면
    낮은 점수를 준다.
    """
    behavior = expected.get("expected_behavior", "")
    behavior_note = (
        "이 케이스는 질문이 과잉진단/단일원인 확정/의료 범위를 벗어난 요청이라 "
        "**확정을 거부하거나 답변을 보류**해야 한다. 생성된 답변이 실제로 확정/진단을 "
        "해버렸다면 반드시 낮은 점수를 줘라."
        if behavior in _RESTRICTIVE_BEHAVIORS
        else f"이 케이스의 기대 행동 유형은 '{behavior}'이다."
    )
    prompt = (
        f"기준 답변: \"{expected['answer']}\"\n"
        f"기대 행동 유형: {behavior}\n{behavior_note}\n\n"
        f"생성된 답변: \"{output['answer']}\"\n\n"
        "생성된 답변이 기준 답변과 핵심 임상 판단이 부합하고, 기대 행동 유형에 맞게 "
        "반응했으며, 과장되거나 진단을 단정하는 표현이 없는지 0.0~1.0 사이 점수로 "
        '평가하라. 문구가 똑같을 필요는 없다. JSON으로만 답하라: '
        '{"score": 0.0~1.0, "explanation": "..."}'
    )
    return _invoke_bedrock_json(prompt)


# ── 실행 ──────────────────────────────────────────────────────────────────────

def _git_short_sha() -> str:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).parent.parent, text=True
        ).strip()
    except Exception:
        return "unknown"


def _git_branch() -> str:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=Path(__file__).parent.parent, text=True
        ).strip()
    except Exception:
        return "unknown"


def main():
    import argparse

    parser = argparse.ArgumentParser(description="RAG 검색 경로 Phoenix Experiment 비교")
    parser.add_argument(
        "--task", choices=["legacy", "new", "both"], default="both",
        help="legacy: retrieve_evidence()만, new: 새 Kiwi+ontology 파이프라인만 "
             "(app.agents.report_generation이 없는 브랜치/커밋에서는 new/both 실행 불가), both: 둘 다",
    )
    args = parser.parse_args()

    base_url = os.environ.get("PHOENIX_BASE_URL", "http://localhost:6006")
    client = Client(base_url=base_url)

    dataset = _retrieval_scoped_dataset(client, DATASET_NAME)
    evaluators = [hit_at_k, recall_at_k, document_relevance, faithfulness, clinical_answer_quality]

    # 실행 시점의 브랜치/커밋을 experiment 이름에 남겨 머지 전/후 비교가 가능하게 한다.
    # 배포된 파드 안에서 실행할 때는 .git이 없으므로 EVAL_TAG로 이미지 태그 등을 넘길 수 있다.
    tag = os.environ.get("EVAL_TAG") or f"{_git_branch()}@{_git_short_sha()}"

    if args.task in ("legacy", "both"):
        print(f"\n=== legacy retrieve_evidence() 실행 (dataset={DATASET_NAME}, {tag}) ===")
        client.experiments.run_experiment(
            dataset=dataset,
            task=task_legacy_retrieve_evidence,
            evaluators=evaluators,
            experiment_name=f"legacy-retrieve-evidence-{tag}",
            experiment_description="Kiwi/ontology/필터 없이 raw 쿼리 임베딩",
        )

    if args.task in ("new", "both"):
        print(f"\n=== 신규 Kiwi+ontology 파이프라인 실행 ({tag}) ===")
        client.experiments.run_experiment(
            dataset=dataset,
            task=task_new_kiwi_ontology_pipeline,
            evaluators=evaluators,
            experiment_name=f"new-kiwi-ontology-pipeline-{tag}",
            experiment_description="Kiwi 형태소 분석 -> ontology 확장 -> 메타데이터 필터 -> 벡터 검색 -> fallback",
        )

    print(f"\nPhoenix UI에서 Datasets > {DATASET_NAME} > Experiments 비교 화면 확인: {base_url}")


if __name__ == "__main__":
    main()
