# RAG 품질 평가 가이드

> 작성일: 2026-06-19  
> 대상: UtterAI RAG 파이프라인 (pgvector + KURE-v1 + LangGraph + Bedrock Claude)

---

## 목차

1. [왜 RAG 품질 평가가 필요한가](#1-왜-rag-품질-평가가-필요한가)
2. [평가 레이어 구조](#2-평가-레이어-구조)
3. [레이어 1: 검색 품질 평가](#3-레이어-1-검색-품질-평가)
4. [레이어 2: 생성 품질 평가 (RAGAS)](#4-레이어-2-생성-품질-평가-ragas)
5. [골든 QA 셋 설계](#5-골든-qa-셋-설계)
6. [수동 검증 빠른 실행 방법](#6-수동-검증-빠른-실행-방법)
7. [현재 할 수 있는 것과 나중에 할 것](#7-현재-할-수-있는-것과-나중에-할-것)
8. [임계값 및 판단 기준](#8-임계값-및-판단-기준)

---

## 1. 왜 RAG 품질 평가가 필요한가

UtterAI의 RAG 파이프라인은 세 단계를 거쳐 SOAP Note를 생성합니다.

```
세션 데이터 입력
       ↓
[검색] pgvector에서 관련 청크 조회 (KURE-v1 임베딩 + 메타데이터 필터)
       ↓
[생성] Bedrock Claude가 검색 결과를 컨텍스트로 SOAP Note 초안 생성
       ↓
SOAP Note 초안 출력
```

각 단계에서 독립적으로 실패할 수 있습니다.

| 실패 지점 | 증상 | 원인 예시 |
|---|---|---|
| 검색 실패 | 잘못된 청크가 반환됨 | 메타데이터 필터 오류, 임베딩 비유사 |
| 컨텍스트 부족 | 관련 청크가 0~1개 | 문서 미비, score_threshold 너무 높음 |
| 생성 실패 | 검색 결과 무시 또는 환각 | 프롬프트 구조 문제, 컨텍스트 너무 짧음 |

평가 없이는 어느 단계가 문제인지 알 수 없습니다. "SOAP Note 품질이 낮다"는 보고가 들어와도 검색 문제인지 생성 문제인지 구분하지 못합니다.

---

## 2. 평가 레이어 구조

RAG 평가는 두 레이어로 분리해 진행합니다.

```
레이어 1: 검색 품질 평가
├── 올바른 청크가 검색되는가?
├── 필터링이 정확히 작동하는가?
└── 빠른 실행, 자동화 가능

레이어 2: 생성 품질 평가 (RAGAS)
├── 검색된 청크가 생성에 반영되는가?
├── 생성 내용이 근거에 충실한가?
└── 시간과 비용 필요, 골든 QA셋 필요
```

레이어 1은 지금 바로 실행 가능합니다. 레이어 2는 문서가 충분히 갖춰진 후(P2/P3 완료 시점) 한 번에 실행하는 것이 효율적입니다.

---

## 3. 레이어 1: 검색 품질 평가

### 3-1. 핵심 지표

#### Recall@K (재현율)

특정 질문에 **반드시 검색되어야 할 문서**가 상위 K개 결과 안에 있는 비율입니다.

```
Recall@5 = (상위 5개 중 정답 청크 수) / (정답 청크 총수)
```

예시:
- 질문: "MLU 계산 시 반복 발화는 어떻게 처리하나요?"
- 정답 청크: `doc_metric_exception_rule`의 "반복 발화 제외 기준" 청크
- Recall@5 = 이 청크가 상위 5개 안에 있으면 1, 없으면 0

목표 기준: `Recall@5 ≥ 0.80` (80%)

#### Precision@K (정밀도)

상위 K개 검색 결과 중 실제로 관련 있는 청크의 비율입니다.

```
Precision@5 = (상위 5개 중 관련 있는 청크 수) / 5
```

관련 있음의 기준: 해당 질문에 답하는 데 직접적으로 기여하는 정보를 포함.

목표 기준: `Precision@5 ≥ 0.60` (60%, 노이즈 청크가 40% 이하)

#### MRR (Mean Reciprocal Rank)

정답 청크가 몇 번째 위치에 처음 등장하는지를 나타냅니다. 1위이면 1.0, 2위이면 0.5, 3위이면 0.33.

```
MRR = 평균(1 / 정답 청크의 첫 번째 순위)
```

목표 기준: `MRR ≥ 0.70`

#### 필터 정확도

`language_area`, `age_group`, `metric` 필터가 올바르게 작동하는지 확인합니다.

- "5세 아동 MLU" 쿼리 → 반환 청크에 `age_group: adult`가 포함되면 안 됨
- "성인 실어증 CIU" 쿼리 → 반환 청크에 `age_group: preschool`이 포함되면 안 됨

목표: 필터 오염률 0% (잘못된 age_group 청크가 결과에 포함되지 않아야 함)

### 3-2. 검색 품질 수동 검증 스크립트

```python
# scripts/eval_retrieval.py
"""
RAG 검색 품질 수동 검증 스크립트.
실행: APP_ENV=local python scripts/eval_retrieval.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

# 검증할 질문과 기대 문서 목록
EVAL_CASES = [
    {
        "query": "MLU 계산할 때 반복 발화는 어떻게 처리해야 하나요?",
        "expected_docs": ["doc_metric_exception_rule", "doc_metric_mlu_korean_rule"],
        "forbidden_age_group": ["adult"],
    },
    {
        "query": "격조사 오류가 많은 만 4세 아동 평가",
        "expected_docs": ["doc_korean_morphosyntax", "doc_language_sample_metrics"],
        "forbidden_age_group": ["adult"],
    },
    {
        "query": "성인 실어증 CIU 분석 결과 해석",
        "expected_docs": ["doc_metric_ciu_korean_rule", "doc_adult_slp_guide"],
        "forbidden_age_group": ["preschool"],
    },
    {
        "query": "리포트에 장애가 있다고 써도 되나요?",
        "expected_docs": ["doc_report_safety_rule"],
        "forbidden_age_group": [],
    },
    {
        "query": "말더듬 아동 중재 방법",
        "expected_docs": ["doc_fluency_guide"],
        "forbidden_age_group": [],
    },
    {
        "query": "초등학교 3학년 이야기 구성 어려움",
        "expected_docs": ["doc_school_age_guide"],
        "forbidden_age_group": [],
    },
    {
        "query": "PRES 수용언어 점수가 표현언어 점수보다 낮아요",
        "expected_docs": ["doc_receptive_language_guide"],
        "forbidden_age_group": ["adult"],
    },
    {
        "query": "단기 목표를 어떻게 작성해야 하나요?",
        "expected_docs": ["doc_goal_writing_guide"],
        "forbidden_age_group": [],
    },
]


async def run_eval():
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.embedding_kure import KUREEmbeddingWrapper
    from app.rag.vector_store import VectorStore
    from app.config import settings
    from app.storage.db import get_engine

    embedding_model = KUREEmbeddingWrapper(model_name=settings.embedding_model_name)
    embedding_model.load()

    results = []
    async with AsyncSession(get_engine()) as session:
        vs = VectorStore(session)

        for case in EVAL_CASES:
            query_vec = embedding_model.embed([case["query"]])[0]
            chunks = await vs.search(query_vec, top_k=5)

            retrieved_docs = [c.metadata.document_id for c in chunks]
            retrieved_age_groups = [c.metadata.age_group for c in chunks]

            # Recall 계산
            hits = sum(1 for doc in case["expected_docs"] if doc in retrieved_docs)
            recall = hits / len(case["expected_docs"]) if case["expected_docs"] else 1.0

            # 필터 오염 확인
            contaminated = any(
                ag in case["forbidden_age_group"]
                for ag in retrieved_age_groups
                if ag is not None
            )

            results.append({
                "query": case["query"][:50],
                "recall": recall,
                "contaminated": contaminated,
                "retrieved": retrieved_docs[:3],
                "expected": case["expected_docs"],
            })

    # 결과 출력
    print(f"\n{'='*70}")
    print(f"{'질문':40} {'Recall':8} {'필터오염':8}")
    print(f"{'-'*70}")
    for r in results:
        status = "❌" if r["contaminated"] else "✅"
        recall_str = f"{r['recall']:.2f}"
        print(f"{r['query']:40} {recall_str:8} {status}")
        if r["recall"] < 1.0:
            print(f"  기대: {r['expected']}")
            print(f"  실제: {r['retrieved']}")

    avg_recall = sum(r["recall"] for r in results) / len(results)
    contamination_count = sum(1 for r in results if r["contaminated"])
    print(f"\n평균 Recall: {avg_recall:.3f}")
    print(f"필터 오염 케이스: {contamination_count}/{len(results)}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    asyncio.run(run_eval())
```

---

## 4. 레이어 2: 생성 품질 평가 (RAGAS)

### 4-1. RAGAS란

RAGAS(Retrieval-Augmented Generation Assessment)는 RAG 파이프라인 전체를 자동 평가하는 Python 라이브러리입니다. 질문, 정답(ground truth), 검색된 컨텍스트, 생성된 답변을 입력받아 품질 지표를 계산합니다.

공식 문서: https://docs.ragas.io

### 4-2. RAGAS 4가지 핵심 지표

#### Context Precision (컨텍스트 정밀도)

검색된 컨텍스트 청크 중 실제로 정답 생성에 필요한 청크의 비율입니다.

```
Context Precision = 관련 청크 수 / 전체 검색된 청크 수
```

이 지표가 낮으면: 검색이 노이즈 청크를 너무 많이 가져옴. 청크 크기, score_threshold, 필터 로직 점검 필요.

목표: `≥ 0.70`

#### Context Recall (컨텍스트 재현율)

정답을 생성하는 데 필요한 정보 중 실제로 검색된 비율입니다.

```
Context Recall = 검색된 필요 정보 / 총 필요 정보
```

이 지표가 낮으면: 필요한 청크가 검색되지 않음. 문서 미비, 임베딩 품질, 필터 과도 적용 점검 필요.

목표: `≥ 0.75`

#### Faithfulness (충실도)

생성된 답변 내용이 검색된 컨텍스트에 근거하는 비율입니다. 환각(hallucination) 탐지 지표입니다.

```
Faithfulness = 컨텍스트로 뒷받침 가능한 주장 수 / 생성 답변의 총 주장 수
```

이 지표가 낮으면: Claude가 컨텍스트를 무시하고 학습 지식으로 답변함. 프롬프트 구조, 컨텍스트 길이 점검 필요.

목표: `≥ 0.80` (임상 서비스이므로 높게 설정)

#### Answer Relevancy (답변 관련성)

생성된 답변이 원래 질문에 얼마나 적합한지를 나타냅니다.

```
Answer Relevancy = 답변과 질문의 코사인 유사도 (LLM으로 역질문 생성 후 비교)
```

이 지표가 낮으면: 질문과 무관한 내용이 생성됨. 프롬프트 또는 검색 결과 문제.

목표: `≥ 0.75`

### 4-3. RAGAS 실행 방법

```python
# scripts/eval_ragas.py
"""
RAGAS를 이용한 RAG 파이프라인 전체 품질 평가.
필요: pip install ragas
실행: APP_ENV=local python scripts/eval_ragas.py
"""
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    context_precision,
    context_recall,
    faithfulness,
    answer_relevancy,
)

# 골든 QA 셋 (docs/eval/golden_qa.json에서 로드)
# 형식: [{"question": ..., "ground_truth": ..., "contexts": [...], "answer": ...}]
import json
with open("docs/eval/golden_qa.json") as f:
    qa_data = json.load(f)

dataset = Dataset.from_list(qa_data)

result = evaluate(
    dataset,
    metrics=[
        context_precision,
        context_recall,
        faithfulness,
        answer_relevancy,
    ],
)

print(result)
# 출력 예:
# {'context_precision': 0.82, 'context_recall': 0.78,
#  'faithfulness': 0.91, 'answer_relevancy': 0.85}
```

### 4-4. RAGAS 데이터셋 구조

```json
[
  {
    "question": "5세 아동의 MLU-m이 2.3인데 어떻게 해석하나요?",
    "contexts": [
      "MLU-m(형태소 단위 평균 발화 길이)은 한국어 아동의 문법 발달을 민감하게 반영한다...",
      "만 5세 기대 범위는 3.5~5.5로, 2.3은 기대 범위 하단보다 낮은 수준이다..."
    ],
    "answer": "이번 회기 MLU-m은 2.3으로, 만 5세 기대 범위(3.5~5.5) 하단보다 낮은 것으로 보입니다. 추가 평가가 권장됩니다.",
    "ground_truth": "MLU-m 2.3은 만 5세 기대 범위 하단보다 낮으며, 이는 표현언어 발달 지연의 소견이 있음을 시사합니다. 단, MLU 단독으로 진단할 수 없으며 종합 평가가 필요합니다."
  }
]
```

`question`: 세션 데이터 또는 임상 질문  
`contexts`: RAG가 실제로 검색한 청크 내용 목록  
`answer`: Bedrock Claude가 생성한 SOAP Note 또는 답변  
`ground_truth`: 전문가(언어재활사)가 작성한 이상적인 답변

---

## 5. 골든 QA 셋 설계

### 5-1. 설계 원칙

골든 QA 셋은 실제 임상 시나리오를 반영해야 합니다. 추상적인 질문이 아니라 UtterAI 사용자가 실제로 입력할 법한 세션 데이터 형태여야 합니다.

**설계 기준**:
- 최소 25문항 (각 임상 영역당 2~3개)
- 연령대 균형: preschool(10개), school_age(5개), adult(7개), all(3개)
- 임상 영역 균형: 표현/수용/음운/형태통사/유창성/담화/목표 작성
- P 섹션(목표 작성) 질문 최소 5개 포함

### 5-2. 질문 유형 분류

| 유형 | 설명 | 예시 |
|---|---|---|
| 지표 해석 | 수치를 받고 임상적 의미 해석 | "MLU-m 2.3, 만 4세 아동" |
| 평가 계획 | 어떤 검사를 해야 하는지 | "수용언어 지연 의심, 다음 평가는?" |
| 중재 방향 | 어떻게 치료할지 | "격조사 오류 많은 아동 중재" |
| 목표 작성 | SOAP Plan 목표 생성 | "PCC 65%, 목표 작성해줘" |
| 안전 규칙 | 표현 제한 확인 | "리포트에 장애가 있다고 써도 되나?" |
| 도구 해석 | 검사 결과 해석 | "PRES 수용 < 표현 차이가 크면?" |

### 5-3. 골든 QA 셋 예시 (25문항 템플릿)

#### 지표 해석 (7개)

```
1. "만 4세 아동, MLU-m 2.1, 형태소 단위 기준. 어떻게 해석하나요?"
   → 기대 문서: doc_metric_mlu_korean_rule, doc_language_sample_metrics
   → 기대 핵심: 만 4세 기대 범위 하단 이하, 표현언어 소견 있음, 단독 진단 불가

2. "성인 실어증 환자, %CIU 52%, CIU/min 45. 심각도는?"
   → 기대 문서: doc_metric_ciu_korean_rule, doc_adult_slp_guide
   → 기대 핵심: 중등도 실어증 범위, 정보 전달 효율성 저하, 기저선으로 전후 비교 권장

3. "PCC 58%, 만 4세 아동. 어떤 오류 패턴을 더 봐야 하나요?"
   → 기대 문서: doc_metric_pcc_korean_rule
   → 기대 핵심: 중등도~심도 범위, 오류 유형 분류(대치/생략/왜곡), 음운변동 분석 권장

4. "P-FA-II %SS 14%, 만 6세 남아. 심각도와 위험 인자는?"
   → 기대 문서: doc_fluency_guide
   → 기대 핵심: 심함 등급, 남아+연령으로 지속 위험 있음, 즉시 중재 권장

5. "PRES 수용언어 등가월령 36개월, 표현언어 48개월. 이 아이의 프로파일은?"
   → 기대 문서: doc_receptive_language_guide
   → 기대 핵심: 표현>수용 불일치, 수용 중재 우선, 수동 조작 과제 중심

6. "LSSC 총점 하위 5백분위, 만 8세 아동. 의미는?"
   → 기대 문서: doc_school_age_guide
   → 기대 핵심: 학령기 언어 전반 지연, DLD 지속 가능성, KOLRA 추가 평가 권장

7. "TTR 0.31, 만 5세 아동. 어휘 다양도 해석은?"
   → 기대 문서: doc_language_sample_metrics
   → 기대 핵심: 어휘 다양도 낮음, 단일 수치 해석 주의, 어휘 중재 검토
```

#### 중재 방향 (6개)

```
8. "말더듬 시작 6개월 된 만 4세 여아. 중재 접근은?"
   → 기대 문서: doc_fluency_guide
   → 기대 핵심: 발병 6개월, 여아 → 자연회복 모니터링 + 리드콤/파린 PCI 고려

9. "격조사 목적격 오류 빈번, 만 5세 아동."
   → 기대 문서: doc_korean_morphosyntax
   → 기대 핵심: 격조사 발달 순서, 목적격 중재 전략

10. "초등 2학년, 이야기 구성 시 배경만 말하고 멈춤."
    → 기대 문서: doc_school_age_guide
    → 기대 핵심: 이야기 구조 교수, story grammar 5요소, 이야기 지도

11. "성인 말더듬, 직장 발표 회피 심함. 중재는?"
    → 기대 문서: doc_fluency_guide
    → 기대 핵심: 성인 말더듬 수정법, ACT, OASES 평가

12. "2단계 지시는 따르는데 3단계 지시는 어려운 만 4세."
    → 기대 문서: doc_receptive_language_guide
    → 기대 핵심: 지시 따르기 3단계, 목표 2→3단계 이동, 수동 조작 과제

13. "ASD 만 6세, 에코랄리아는 있지만 이해가 어려움."
    → 기대 문서: doc_child_slp_population, doc_receptive_language_guide
    → 기대 핵심: 표현>수용 프로파일, 수용 중재 우선
```

#### 목표 작성 (5개)

```
14. "PCC 65%, 만 4세 아동. 단기 목표를 작성해주세요."
    → 기대 문서: doc_goal_writing_guide, doc_metric_pcc_korean_rule
    → 기대 핵심: 목표 자음 특정, 단서 수준 명시, 80% 기준, 2개월 기간

15. "MLU-m 2.1, 만 4세 아동. SMART 목표 작성."
    → 기대 문서: doc_goal_writing_guide
    → 기대 핵심: 격조사 포함 2어절, 최소 단서, 10시도 8회, 3개월

16. "초등 3학년 이야기 구성 중재 목표."
    → 기대 문서: doc_goal_writing_guide, doc_school_age_guide
    → 기대 핵심: 5요소 이야기, 3회기 연속, 활동 수준 목표

17. "성인 실어증 참여 수준 목표 작성."
    → 기대 문서: doc_goal_writing_guide
    → 기대 핵심: ICF 참여 수준, 일상 의사소통 상황, 가정/직장

18. "말더듬 성인 단기 목표."
    → 기대 문서: doc_goal_writing_guide, doc_fluency_guide
    → 기대 핵심: Soft Onset 적용률, % SS 기준, 치료 상황 명시
```

#### 안전 규칙 (4개)

```
19. "MLU가 낮으니 언어발달지연이 있다고 써도 되나요?"
    → 기대 문서: doc_report_safety_rule
    → 기대 핵심: 단정 표현 금지, "소견이 있다/시사된다"로 대체

20. "PCC 결과로 조음장애로 진단된다고 쓰려는데요."
    → 기대 문서: doc_report_safety_rule
    → 기대 핵심: 수치 기반 단정 금지, AI 진단 권한 없음

21. "이 아이는 반드시 DLD입니다 — 이 표현 괜찮나요?"
    → 기대 문서: doc_report_safety_rule
    → 기대 핵심: 진단 확정 표현 금지, 추가 평가 권장 표현 사용

22. "보고서 마지막에 뭘 꼭 써야 하나요?"
    → 기대 문서: doc_report_safety_rule
    → 기대 핵심: AI 초안 명시 의무, 담당 언어재활사 검토 문구
```

#### 계산 규칙 (3개)

```
23. "MLU 계산 시 간투사(음, 어)는 어떻게 처리하나요?"
    → 기대 문서: doc_metric_exception_rule
    → 기대 핵심: 의미 없이 독립 사용 시 제외

24. "CIU 계산 시 착어 발화는 포함하나요?"
    → 기대 문서: doc_metric_ciu_korean_rule
    → 기대 핵심: 원칙적 제외, 정보 명확히 전달된 경우 임상 판단

25. "PCC 계산 시 모음은 어떻게 하나요?"
    → 기대 문서: doc_metric_pcc_korean_rule
    → 기대 핵심: 모음 제외, 자음 19개만 대상
```

---

## 6. 수동 검증 빠른 실행 방법

RAGAS 전에 빠르게 검색 품질을 확인하는 방법입니다. 로컬 환경에서 10분 이내에 실행 가능합니다.

### 단계 1: 인제스트 확인

```bash
# 모든 문서가 인제스트됐는지 확인
APP_ENV=local python -c "
import asyncio, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.storage.db import get_engine

async def check():
    async with AsyncSession(get_engine()) as s:
        r = await s.execute(text('SELECT document_id, COUNT(*) as chunks FROM rag_chunks GROUP BY document_id ORDER BY document_id'))
        for row in r:
            print(f'{row.document_id:45} {row.chunks:3}개 청크')
asyncio.run(check())
"
```

기대 출력 예:
```
doc_adult_slp_guide                           18개 청크
doc_child_assessment_tools                    12개 청크
doc_fluency_guide                             22개 청크
doc_goal_writing_guide                        15개 청크
...
```

### 단계 2: 직접 쿼리 테스트

```bash
APP_ENV=local python -c "
import asyncio, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()

async def test():
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.embedding_kure import KUREEmbeddingWrapper
    from app.rag.vector_store import VectorStore
    from app.config import settings
    from app.storage.db import get_engine

    em = KUREEmbeddingWrapper(model_name=settings.embedding_model_name)
    em.load()

    queries = [
        'MLU 계산 시 반복 발화 처리 방법',
        '말더듬 아동 중재',
        '리포트에 장애가 있다고 써도 되나',
        '초등학생 이야기 구성 어려움',
        '단기 목표 SMART 작성',
    ]

    async with AsyncSession(get_engine()) as session:
        vs = VectorStore(session)
        for q in queries:
            vec = em.embed([q])[0]
            chunks = await vs.search(vec, top_k=3)
            print(f'\n질문: {q}')
            for i, c in enumerate(chunks, 1):
                print(f'  {i}. [{c.metadata.document_id}] score={c.score:.3f}')
                print(f'     {c.content[:80]}...')

asyncio.run(test())
"
```

### 단계 3: 필터 오염 확인

```bash
APP_ENV=local python scripts/eval_retrieval.py
```

---

## 7. 현재 할 수 있는 것과 나중에 할 것

### 지금 바로 할 수 있는 것 (레이어 1)

| 작업 | 소요 시간 | 필요 준비 |
|---|---|---|
| 인제스트 확인 | 5분 | 로컬 DB + 인제스트 완료 |
| 직접 쿼리 테스트 | 10분 | 로컬 DB |
| `eval_retrieval.py` 실행 | 20분 | 로컬 DB + 위 스크립트 |

### P2/P3 문서 추가 후 할 것 (레이어 2)

| 작업 | 소요 시간 | 필요 준비 |
|---|---|---|
| 골든 QA 셋 작성 | 2~4시간 | 언어재활사 검토 권장 |
| RAGAS 평가 실행 | 30분~1시간 | `pip install ragas`, Bedrock 접근 |
| 결과 분석 및 개선 | 조건부 | RAGAS 점수 기준 미달 항목 |

### 평가 실행 권장 시점

```
현재 (Stage 3 완료)
  → 레이어 1 수동 검증 실행 (지금 바로)

Stage 4 (논문 수집) 완료 후
  → 레이어 1 재실행 (새 문서 포함 검색 품질 확인)

Stage 5 (P2/P3 문서) 완료 후
  → 골든 QA 셋 작성 + RAGAS 레이어 2 최초 실행
  → 기준점(baseline) 확보

이후 문서 추가마다
  → RAGAS 재실행으로 품질 회귀 확인
```

---

## 8. 임계값 및 판단 기준

### 레이어 1 합격 기준

| 지표 | 목표 | 개선 조치 |
|---|---|---|
| Recall@5 | ≥ 0.80 | 문서 내용 보강 또는 ontology 확장 |
| Precision@5 | ≥ 0.60 | score_threshold 조정, 필터 강화 |
| MRR | ≥ 0.70 | 임베딩 모델 재검토 또는 청크 크기 조정 |
| 필터 오염률 | 0% | vector_store.py 필터 로직 점검 |

### 레이어 2 합격 기준 (RAGAS)

| 지표 | 목표 | 미달 시 점검 |
|---|---|---|
| Context Precision | ≥ 0.70 | 청크 크기, score_threshold, 필터 |
| Context Recall | ≥ 0.75 | 문서 미비, 임베딩 품질, 필터 과잉 |
| Faithfulness | ≥ 0.80 | 프롬프트 구조, 컨텍스트 길이 |
| Answer Relevancy | ≥ 0.75 | 프롬프트 또는 검색 결과 |

### 문서 추가 시 품질 회귀 기준

새 문서를 추가한 후 기존 질문의 점수가 하락하면 회귀로 판단합니다.

회귀 기준: 기존 점수 대비 Recall@5 -0.05 이상 하락, 또는 필터 오염 케이스 증가.

회귀 원인: 새 문서의 메타데이터 오류로 기존 필터 작동 방해, 새 청크가 기존 관련 청크의 유사도 순위를 밀어냄.

---

## 부록: 용어 정리

| 용어 | 설명 |
|---|---|
| RAG | Retrieval-Augmented Generation. 검색 결과를 컨텍스트로 사용하는 LLM 생성 방식 |
| pgvector | PostgreSQL에서 벡터 유사도 검색을 지원하는 확장 |
| KURE-v1 | 한국어 특화 임베딩 모델 (nlpai-lab/KURE-v1, 1024차원) |
| Chunk | 문서를 검색 단위로 분할한 텍스트 조각 |
| Recall@K | 정답 청크가 상위 K개 안에 있는 비율 |
| Precision@K | 상위 K개 중 관련 청크 비율 |
| MRR | Mean Reciprocal Rank. 정답의 평균 역순위 |
| RAGAS | RAG 파이프라인 자동 평가 라이브러리 |
| Context Precision | 검색된 컨텍스트의 관련성 비율 |
| Context Recall | 필요한 정보의 검색 완성도 |
| Faithfulness | 생성 답변의 근거 충실도 (환각 탐지) |
| Answer Relevancy | 답변과 질문의 적합도 |
| Golden QA Set | 평가용 표준 질문-정답 셋 |
| Hallucination | LLM이 근거 없이 내용을 만들어내는 현상 |