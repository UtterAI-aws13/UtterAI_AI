# ADR-001: RAG 파이프라인을 Agentic RAG으로 고도화

| 항목 | 내용 |
|---|---|
| **상태** | Proposed |
| **작성일** | 2026-06-28 |
| **결정자** | UtterAI AI 팀 |
| **관련 파일** | `app/rag/rag_graph.py`, `app/rag/retriever.py`, `app/pipelines/bedrock_client.py`, `app/pipelines/report_pipeline.py` |

---

## 1. 배경 및 문제 정의

### 현재 RAG 파이프라인

현재 RAG는 `LangGraph StateGraph` 기반이지만, 검색 재시도 판단이 **LLM이 아닌 규칙**으로 구현되어 있다.

```
현재 흐름 (rag_graph.py):
  extract_keywords → expand_query → retrieve
                                       │
                      score ≥ 2개?  ──┤
                         YES ↓        ↓ NO
                       finalize   fallback_retrieve
                                  (필터 제거 + top_k×2)
                                       ↓
                                   finalize (강제 종료)
```

- `route_evidence()`: score 카운트 기반 하드코딩, LLM 판단 없음
- `expand_query()`: `ontology.yaml` 딕셔너리 lookup, LLM 없음
- `fallback_retrieve()`: 사전에 정해진 전략(필터 제거), 동적 판단 없음

이 구조는 **Adaptive RAG**에 가깝고, 진정한 Agentic RAG가 아니다.

### 현재 구조의 한계

1. **쿼리 재작성 불가**: 검색 실패 시 필터를 제거하는 것이 전부, 다른 관점으로 질문을 재구성하지 못함
2. **근거 품질 판단 불가**: 점수 임계값으로만 판단, "이 내용이 MLU 해석에 실제로 유용한가" 판단 불가
3. **검색 횟수 고정**: 1회 재시도만 가능, 복잡한 임상 쿼리에서 다중 전략 시도 불가
4. **세션 연속성 없음**: 이전 세션의 임상 맥락(MLU 변화 추이, 이전 중재 전략)을 기억하지 못함
5. **임상 안전 규칙 강제 불가**: "진단 단정 금지" 같은 규칙이 시스템 수준에서 강제되지 않음

---

## 2. 결정 요인

- **임상 도메인 정확성**: 소아 언어치료 SOAP Note의 잘못된 해석은 직접적인 의료적 영향을 미침
- **한국어 임베딩 품질 유지**: KURE-v1은 한국어 임상 텍스트에 특화, 대체 불가
- **HIPAA 대비**: 임상 데이터 처리 서비스로 확장 시 규정 준수 요건
- **운영 비용**: 현재 AWS 인프라(RDS pgvector, Bedrock, SQS) 최대 활용
- **구현 복잡도**: 팀 규모와 일정에 맞는 현실적 방안

---

## 3. 검토한 옵션

### Option 1: 현상 유지 (규칙 기반 Adaptive RAG)

현재 `rag_graph.py` 구조를 유지한다.

**장점:** 추가 개발 없음, 안정적  
**단점:** 위에 나열한 한계 그대로 유지, 임상 품질 개선 불가

---

### Option 2: Bedrock Tool Use (인라인 Agentic RAG)

`bedrock-runtime`의 `tool_use` 파라미터를 활용해 Claude가 직접 검색 여부를 판단하도록 변경.

```python
# bedrock_client.py에 tools 정의 추가
tools = [{
    "name": "search_evidence",
    "description": "언어치료 임상 근거를 pgvector에서 검색",
    "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}
}]
```

**장점:** 기존 `bedrock_client.py` 수정만으로 적용, KURE-v1 유지, 추가 비용 최소  
**단점:** 세션 메모리 없음(별도 구현 필요), 임상 안전 규칙 미강제, 모니터링 수동 구축 필요

---

### Option 3: Amazon Bedrock AgentCore (선택)

AgentCore Runtime을 에이전트 오케스트레이션 계층으로 사용하고, KURE-v1 + pgvector 검색은 Lambda로 wrapping해 AgentCore Tool로 등록.

```
AgentCore Runtime (Claude)
  │
  ├─ Tool: search_evidence  →  Lambda  →  KURE-v1 임베딩 + pgvector 검색
  │
  ├─ Memory: 세션 에피소딕 기억 (환자 이전 세션 MLU 추이)
  │
  └─ Policy (Cedar): "진단 단정 금지", "PII 노출 금지" 실시간 강제
```

**장점:** 진정한 LLM 기반 Agentic RAG, 세션 메모리, 임상 안전 정책, HIPAA eligible, 에이전트 루프 관리 자동화  
**단점:** KURE-v1 Lambda wrapping 필요(구현 공수), AgentCore 추가 과금, 학습 곡선

---

## 4. 결정: Option 3 — Amazon Bedrock AgentCore

### 근거

**Option 2 대비 AgentCore를 선택하는 이유:**

| 기능 | Option 2 (Tool Use) | Option 3 (AgentCore) |
|---|---|---|
| LLM 기반 검색 판단 | ✅ | ✅ |
| 세션 간 환자 기억 | ❌ (RDS 직접 구현) | ✅ (Memory 기본 제공) |
| 임상 안전 정책 강제 | ❌ (Guardrails 별도) | ✅ (Cedar Policy) |
| HIPAA eligible | 부분적 | ✅ |
| 에이전트 루프 관리 | 직접 구현 | ✅ 자동화 |
| 모니터링 | 직접 구축 | ✅ CloudWatch 통합 |

세션 메모리와 Policy는 나중에 추가하기 어렵고, AgentCore의 Managed Harness(2026.04)로 구현 복잡도가 크게 낮아졌다.

### KURE-v1 Lambda wrapping 비용 분석

Lambda 프리티어(월 100만 건 요청, 400,000 GB-초)로 현재 규모에서 **Lambda 비용은 사실상 0**.  
Cold start 이슈는 EventBridge 워밍업(5분 간격, 무료)으로 대응.

---

## 5. 아키텍처 변경

### AS-IS

```
report_pipeline.py
  │
  ├─ retrieve_evidence()          # 규칙 기반 벡터 검색 (LLM 없음)
  │     └─ rag_graph.py           # LangGraph StateGraph
  │
  └─ invoke_claude(prompt)        # Bedrock Claude (리포트 생성만)
```

### TO-BE

```
report_pipeline.py
  │
  └─ agentcore_client.invoke_agent(session_data)
        │
        └─ AgentCore Runtime (Claude)
              │  ← 에이전트 루프: 검색 필요 시 tool 호출, 충분하면 리포트 생성
              │  ← Memory: 이전 세션 임상 맥락 자동 주입
              │  ← Policy: 임상 안전 규칙 실시간 강제
              │
              └─ Tool: search_evidence
                    └─ Lambda: kure-retriever
                          ├─ KURE-v1 임베딩 (기존 유지)
                          └─ pgvector 검색 (기존 유지)
```

---

## 6. 결과 및 트레이드오프

### 긍정적 결과

- Claude가 "MLU 기준 근거를 먼저 찾고, 이후 중재 전략을 추가 검색"하는 등 다단계 추론 가능
- 에피소딕 메모리로 "3주 전보다 MLU 0.4 향상" 같은 세션 간 맥락이 SOAP Note에 반영
- Cedar Policy로 "진단 단정 금지" 규칙이 모든 에이전트 실행에 자동 적용
- `rag_graph.py` (LangGraph 오케스트레이션 코드) 제거 가능

### 부정적 결과 / 완화 방안

| 리스크 | 완화 방안 |
|---|---|
| Lambda cold start (~2–4초) | EventBridge 5분 주기 워밍업 |
| AgentCore 추가 과금 | Haiku로 tool 판단, Sonnet은 최종 생성만 |
| KURE-v1 Lambda 통합 공수 | 기존 `retrieve_evidence()` 로직 그대로 이식 |
| 벤더 락인 심화 | Lambda 내부 도메인 로직(ontology, chunker) 완전 독립 유지 |

---

## 7. 비용 분석

### 현재 구조 (AS-IS) 월간 비용

| 항목 | 단가 (Amazon Bedrock) | 예상 사용량 (500 세션/월) | 월 비용 |
|---|---|---|---|
| Claude Haiku 4.5 — 입력 | $1.00 / 1M 토큰 | 1.75M 토큰 | $1.75 |
| Claude Haiku 4.5 — 출력 | $5.00 / 1M 토큰 | 0.6M 토큰 | $3.00 |
| **합계** | | | **~$4.75/월** |

### AgentCore 컴포넌트 단가

| 컴포넌트 | 항목 | 단가 |
|---|---|---|
| **Runtime** | vCPU 사용 | $0.0895 / vCPU-시간 |
| **Runtime** | 메모리 사용 | $0.00945 / GB-시간 |
| **Gateway** | Tool 호출 | $0.005 / 1,000건 |
| **Gateway** | Tool 등록 | $0.02 / 100개/월 |
| **Memory** | 에피소딕 조회 | $0.50 / 1,000건 |
| **Memory** | 장기 자동 메모리 | $0.75 / 1,000건 |
| **Policy** | Cedar 정책 평가 | $0.000025 / 건 |
| **Identity** | Runtime/Gateway 경유 | 무료 |

### Claude 모델 단가 (Amazon Bedrock)

| 모델 | 입력 | 출력 | UtterAI 권장 용도 |
|---|---|---|---|
| Claude Haiku 4.5 | $1.00 / 1M 토큰 | $5.00 / 1M 토큰 | tool 호출 판단 + SOAP Note 생성 (기본) |
| Claude Sonnet 4.6 | $3.00 / 1M 토큰 | $15.00 / 1M 토큰 | 복잡한 임상 케이스 (선택적 적용) |

> 현재 `app/config.py`의 `bedrock_report_model_id`가 Haiku 4.5이므로 TO-BE에서도 Haiku 기본값 유지.  
> Sonnet은 tool 호출 5회 이상 복잡한 세션에만 선택적으로 사용하면 비용을 통제할 수 있다.

### AgentCore 전환 후 월간 비용 추정 (500 세션/월)

| 항목 | 계산 근거 | 월 비용 |
|---|---|---|
| Lambda (KURE-v1 검색) | 1,500건 × 30 GB-초 = 45,000 GB-초 → 프리티어(400,000 GB-초/월) 내 | **$0** |
| Claude Haiku 4.5 입력 | 500세션 × 3,500 토큰 = 1.75M × $1.00/1M | $1.75 |
| Claude Haiku 4.5 출력 | 500세션 × 1,200 토큰 = 0.60M × $5.00/1M | $3.00 |
| AgentCore Runtime (vCPU) | 500세션 × 1분/세션 ≈ 8.3 vCPU-시간 × $0.0895 | $0.74 |
| AgentCore Runtime (메모리) | 8.3 × 2 GB-시간 × $0.00945 | $0.16 |
| AgentCore Gateway | 1,500 tool 호출 × $0.005/1,000 | $0.01 |
| AgentCore Memory | 500 에피소딕 조회 × $0.50/1,000 | $0.25 |
| AgentCore Policy | 500건 × $0.000025 | $0.01 |
| **합계** | | **~$5.92/월** |

### 비용 비교 요약

| | AS-IS | TO-BE | 차이 |
|---|---|---|---|
| 월 비용 (500 세션) | ~$4.75 | ~$5.92 | +$1.17 (+25%) |
| 세션당 단가 | ~$0.0095 | ~$0.0118 | +$0.0023 |
| 세션 간 환자 메모리 | ❌ | ✅ | — |
| 임상 안전 정책 강제 | ❌ | ✅ | — |
| HIPAA 적격 인프라 | 부분적 | ✅ | — |
| LLM 기반 검색 판단 | ❌ | ✅ | — |

**결론:** 세션당 약 $0.002(약 3원)의 추가 비용으로 세션 메모리, 임상 안전 정책, HIPAA 적격 인프라를 확보한다.  
Lambda 프리티어 덕분에 KURE-v1 검색 비용은 현재 규모에서 사실상 $0이다.

> 위 수치는 AWS 공개 요금표 기준 추정치이며, 리전·계약 유형에 따라 달라질 수 있다.  
> 상세 요금은 [AWS Pricing Calculator](https://calculator.aws/pricing/2/home) 또는 [AgentCore 요금 페이지](https://aws.amazon.com/bedrock/agentcore/pricing/)에서 확인한다.

---

## 8. 관련 문서

- [AGENTIC_RAG_GUIDE.md](./AGENTIC_RAG_GUIDE.md) — 구현 가이드
- [RAG_IMPLEMENTATION.md](./RAG_IMPLEMENTATION.md) — 기존 RAG 구현 상세
- [RAG_GUIDE.md](./RAG_GUIDE.md) — RAG 운영 가이드
