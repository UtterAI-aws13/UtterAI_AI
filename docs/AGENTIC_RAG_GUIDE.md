# Agentic RAG 고도화 구현 가이드

> 관련 ADR: [ADR-001-agentic-rag.md](./ADR-001-agentic-rag.md)

---

## 목차

1. [전체 아키텍처](#1-전체-아키텍처)
2. [구현 단계 개요](#2-구현-단계-개요)
3. [Step 1: KURE-v1 Lambda 생성](#3-step-1-kure-v1-lambda-생성)
4. [Step 2: AgentCore Gateway에 Tool 등록](#4-step-2-agentcore-gateway에-tool-등록)
5. [Step 3: AgentCore Runtime 구성](#5-step-3-agentcore-runtime-구성)
6. [Step 4: Memory 설정](#6-step-4-memory-설정)
7. [Step 5: Policy 설정](#7-step-5-policy-설정)
8. [Step 6: agentcore_client.py 작성](#8-step-6-agentcore_clientpy-작성)
9. [Step 7: report_pipeline 연결](#9-step-7-report_pipeline-연결)
10. [검증 및 테스트](#10-검증-및-테스트)
11. [삭제 대상 코드](#11-삭제-대상-코드)
12. [비용 가이드](#12-비용-가이드)

---

## 1. 전체 아키텍처

```
[report_pipeline.py]
        │
        ▼
[agentcore_client.py]   ← 신규 작성
        │
        ▼
[AgentCore Runtime]     ← Claude가 에이전트 루프 주도
        │  ┌─────────────────────────────────────────────┐
        │  │ 1. session_data 분석                         │
        │  │ 2. search_evidence tool 호출 (필요 시 반복)   │
        │  │ 3. 근거 충분 판단 → SOAP Note 생성            │
        │  └─────────────────────────────────────────────┘
        │
        ├── [AgentCore Memory]   에피소딕 메모리 (환자 세션 이력)
        ├── [AgentCore Policy]   Cedar 임상 안전 규칙
        │
        └── [AgentCore Gateway]
                │
                ▼
        [Lambda: kure-retriever]   ← 기존 로직 재사용
                │
                ├── KURE-v1 임베딩 (nlpai-lab/KURE-v1)
                └── pgvector 검색 (RDS PostgreSQL)
```

---

## 2. 구현 단계 개요

| 단계 | 작업 | 변경 파일 | 난이도 |
|---|---|---|---|
| Step 1 | KURE-v1 Lambda 생성 | 신규 Lambda 함수 | 중 |
| Step 2 | AgentCore Tool 등록 | AWS 콘솔 / CDK | 하 |
| Step 3 | AgentCore Runtime 구성 | AWS 콘솔 / CDK | 하 |
| Step 4 | Memory 설정 | AWS 콘솔 | 하 |
| Step 5 | Policy 설정 | Cedar 정책 파일 | 중 |
| Step 6 | agentcore_client.py 작성 | 신규 | 중 |
| Step 7 | report_pipeline 연결 | `report_pipeline.py` | 하 |

---

## 3. Step 1: KURE-v1 Lambda 생성

기존 `app/rag/retriever.py`의 `retrieve_evidence()` 로직을 Lambda로 이식한다.  
코드 재작성 없이 **함수를 그대로 옮기는 수준**이다.

### 3.1 Lambda 핸들러 작성

```python
# lambda/kure_retriever/handler.py
import json
import asyncio
from app.rag.retriever import retrieve_evidence

def lambda_handler(event: dict, context) -> dict:
    """
    AgentCore Gateway에서 호출되는 엔트리포인트.

    event 예시:
    {
        "query": "만 3세 MLU 2.1, TTR 0.42 아동 표현언어 중재 방법",
        "top_k": 5
    }
    """
    query = event.get("query", "")
    top_k = event.get("top_k", 5)

    # retrieve_evidence는 async 함수이므로 asyncio.run으로 실행
    results = asyncio.run(
        retrieve_evidence(
            metrics={},          # query 직접 전달 모드
            session={},
            top_k=top_k,
            direct_query=query,  # retrieve_evidence에 direct_query 파라미터 추가 필요 (Step 1.2 참조)
        )
    )

    return {
        "statusCode": 200,
        "body": json.dumps(results, ensure_ascii=False)
    }
```

### 3.2 retrieve_evidence 수정 (direct_query 파라미터 추가)

```python
# app/rag/retriever.py
async def retrieve_evidence(
    metrics: dict,
    session: dict,
    top_k: int = 5,
    embedding_model: KUREEmbeddingWrapper | None = None,
    direct_query: str | None = None,   # ← 추가
) -> list[dict]:
    ...
    # direct_query가 있으면 그대로 사용, 없으면 기존 지표 기반 쿼리 생성
    if direct_query:
        question = direct_query
    else:
        age_months = session.get("patient_age_months", 0)
        mlu = metrics.get("mlu_word", metrics.get("mlu_morpheme", 0))
        ...
        question = f"만 {age_months // 12}세 아동 언어치료 세션. MLU {mlu:.1f} ..."
```

### 3.3 Lambda 배포 설정

```yaml
# lambda/kure-retriever/template.yaml (SAM)
Resources:
  KureRetrieverFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: utterai-kure-retriever
      Handler: handler.lambda_handler
      Runtime: python3.12
      MemorySize: 3008        # KURE-v1 모델 로딩을 위해 3GB
      Timeout: 30
      PackageType: Image      # 모델 크기로 인해 컨테이너 이미지 방식 사용
      ImageUri: !Sub "${AWS::AccountId}.dkr.ecr.ap-northeast-2.amazonaws.com/utterai-kure-retriever:latest"
      Environment:
        Variables:
          DB_HOST: !Ref RdsEndpoint
          DB_NAME: utterai
```

### 3.4 Cold Start 워밍업 (비용 없이)

```yaml
# EventBridge 규칙: 5분마다 Lambda 호출
WarmupRule:
  Type: AWS::Events::Rule
  Properties:
    ScheduleExpression: "rate(5 minutes)"
    Targets:
      - Arn: !GetAtt KureRetrieverFunction.Arn
        Input: '{"query": "ping", "top_k": 1}'
```

---

## 4. Step 2: AgentCore Gateway에 Tool 등록

AgentCore가 Lambda를 tool로 호출할 수 있도록 Gateway에 등록한다.

### OpenAPI schema 정의

```json
{
  "openapi": "3.0.0",
  "info": { "title": "KURE Retriever", "version": "1.0.0" },
  "paths": {
    "/search": {
      "post": {
        "operationId": "search_evidence",
        "summary": "언어치료 임상 근거를 한국어 임베딩(KURE-v1)으로 검색",
        "description": "환자 세션 지표(MLU, TTR, NDW 등)나 자연어 쿼리로 관련 임상 문서를 검색한다. 근거가 부족하다고 판단되면 다른 쿼리로 재호출할 수 있다.",
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "query": {
                    "type": "string",
                    "description": "검색할 임상 쿼리. 예: '만 3세 MLU 2.1 표현언어 중재', 'TTR 0.35 어휘 다양도 해석'"
                  },
                  "top_k": {
                    "type": "integer",
                    "default": 5,
                    "description": "반환할 최대 근거 수"
                  }
                },
                "required": ["query"]
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "검색된 임상 근거 목록",
            "content": {
              "application/json": {
                "schema": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "chunk_id": { "type": "string" },
                      "title": { "type": "string" },
                      "content": { "type": "string" },
                      "score": { "type": "number" }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

### AWS CLI로 등록

```bash
aws bedrock-agentcore create-tool \
  --name "kure-evidence-retriever" \
  --description "KURE-v1 기반 언어치료 임상 근거 검색" \
  --lambda-arn "arn:aws:lambda:ap-northeast-2:ACCOUNT_ID:function:utterai-kure-retriever" \
  --api-schema file://openapi-schema.json \
  --region ap-northeast-2
```

---

## 5. Step 3: AgentCore Runtime 구성

### Managed Harness 방식 (권장)

```yaml
# agentcore-config.yaml
model: us.anthropic.claude-haiku-4-5-20251001-v1:0   # 기존 config 그대로
maxIterations: 5    # tool 호출 최대 5회
systemPrompt: |
  당신은 소아 언어치료 전문 보조 에이전트입니다.
  세션 지표(MLU, TTR, NDW, 반응지연)를 분석하고 SOAP Note를 작성합니다.

  지침:
  - search_evidence tool을 사용해 관련 임상 근거를 반드시 먼저 검색하세요.
  - 근거가 불충분하다고 판단되면 다른 관점의 쿼리로 재검색하세요.
  - 진단을 단정하지 마세요. "시사한다", "가능성이 있다" 등의 표현을 사용하세요.
  - 모든 해석은 검색된 임상 근거를 기반으로 작성하세요.

tools:
  - toolId: "kure-evidence-retriever"

memory:
  enabled: true
  type: episodic

policy:
  policyId: "utterai-clinical-policy"
```

---

## 6. Step 4: Memory 설정

AgentCore Memory는 환자 세션 이력을 에피소딕으로 저장해, 다음 세션 호출 시 자동으로 컨텍스트를 주입한다.

```python
# agentcore_client.py에서 호출 시 session_id 전달
response = agentcore_client.invoke_agent(
    agentId=AGENT_ID,
    sessionId=f"patient-{patient_id}",   # ← 환자별 고유 세션 ID
    inputText=prompt,
)
```

`sessionId`를 환자 ID 기반으로 설정하면 AgentCore Memory가 해당 환자의 이전 세션 요약을 자동으로 불러와 에이전트에게 제공한다.

**기대 효과:**
- "지난 세션 대비 MLU 0.4 향상" 자동 반영
- 이전 중재 전략의 효과를 현재 세션에 연속적으로 기술

---

## 7. Step 5: Policy 설정

Cedar 정책으로 임상 안전 규칙을 에이전트 실행 레벨에서 강제한다.

```cedar
// utterai-clinical-policy.cedar

// 진단 단정 표현 금지
forbid(
  principal,
  action == AgentCore::Action::"generate_response",
  resource
) when {
  context.response_text.contains("확진") ||
  context.response_text.contains("진단: ") ||
  context.response_text.contains("장애입니다")
};

// tool 호출 없이 바로 응답 생성 금지 (반드시 근거 검색 선행)
forbid(
  principal,
  action == AgentCore::Action::"generate_response",
  resource
) when {
  context.tool_calls_count == 0
};
```

---

## 8. Step 6: agentcore_client.py 작성

기존 `app/pipelines/bedrock_client.py`를 대체한다.

```python
# app/pipelines/agentcore_client.py
import json
import boto3
from loguru import logger
from app.config import settings

_client = None

AGENT_ID = "utterai-soap-agent"      # AgentCore에서 생성한 Agent ID
AGENT_ALIAS = "PROD"


def get_agentcore_client():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-agentcore-runtime", region_name=settings.bedrock_region)
    return _client


def invoke_agent(
    prompt: str,
    patient_id: str,
    max_tokens: int = 2048,
) -> dict:
    """
    AgentCore Runtime을 호출한다.
    - Claude가 search_evidence tool을 필요한 만큼 호출한 뒤 SOAP Note를 생성
    - Memory가 patient_id 기반으로 이전 세션 컨텍스트를 자동 주입
    """
    client = get_agentcore_client()
    session_id = f"patient-{patient_id}"

    logger.info(f"[agentcore] invoke_agent 시작 patient_id={patient_id}")

    response = client.invoke_agent(
        agentId=AGENT_ID,
        agentAliasId=AGENT_ALIAS,
        sessionId=session_id,
        inputText=prompt,
        sessionState={
            "sessionAttributes": {
                "max_tokens": str(max_tokens),
            }
        },
    )

    # AgentCore 응답은 스트리밍 이벤트 스트림
    full_text = ""
    for event in response.get("completion", []):
        if "chunk" in event:
            chunk_text = event["chunk"]["bytes"].decode("utf-8")
            full_text += chunk_text

    logger.info(f"[agentcore] 응답 수신 완료 text_len={len(full_text)}")
    return _parse_json(full_text)


def _parse_json(text: str) -> dict:
    # 기존 bedrock_client.py의 _parse_json 그대로 재사용
    import re
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {
        "soap_note": {"subjective": "", "objective": text, "assessment": "", "plan": ""},
        "parse_error": True,
        "disclaimer": "치료사 검토가 필요한 AI 생성 초안입니다.",
    }
```

---

## 9. Step 7: report_pipeline 연결

`report_pipeline.py`에서 `bedrock_client` 대신 `agentcore_client`를 사용하도록 변경한다.

```python
# app/pipelines/report_pipeline.py

# 변경 전
from app.pipelines.bedrock_client import invoke_claude

# 변경 후
from app.pipelines.agentcore_client import invoke_agent
```

```python
# 변경 전
rag_evidence = await retrieve_evidence(metrics, session)
prompt = build_prompt(metrics, session, rag_evidence)
result = invoke_claude(prompt)

# 변경 후
# RAG 검색과 리포트 생성을 AgentCore가 통합 처리
prompt = build_session_prompt(metrics, session)   # 근거 없이 세션 정보만 전달
result = invoke_agent(
    prompt=prompt,
    patient_id=session.get("patient_id", "unknown"),
)
```

`build_session_prompt`는 기존 `build_prompt`에서 RAG evidence 주입 부분만 제거한 버전이다. 근거 검색은 AgentCore가 tool을 통해 직접 수행한다.

---

## 10. 검증 및 테스트

### 10.1 Lambda 단독 테스트

```bash
aws lambda invoke \
  --function-name utterai-kure-retriever \
  --payload '{"query": "만 3세 MLU 2.1 표현언어 중재 방법", "top_k": 3}' \
  --cli-binary-format raw-in-base64-out \
  response.json

cat response.json
```

기대 결과: score > 0.5인 임상 근거 3건 반환

### 10.2 AgentCore tool 호출 추적

AgentCore는 CloudWatch에 에이전트 실행 트레이스를 자동 기록한다.

```bash
aws logs filter-log-events \
  --log-group-name "/aws/bedrock-agentcore/utterai-soap-agent" \
  --filter-pattern "tool_use"
```

tool 호출 횟수, 각 쿼리, 응답 점수를 확인해 에이전트가 올바르게 검색하는지 검증한다.

### 10.3 기존 리포트 품질 비교

```python
# scripts/eval_agentic_rag.py
# 동일한 세션 데이터로 기존 방식과 AgentCore 방식의 SOAP Note를 비교

test_session = {
    "patient_id": "test-001",
    "patient_age_months": 36,
    "mlu_word": 2.1,
    "ttr": 0.38,
    "ndw": 45,
    "avg_response_latency_sec": 1.8,
}

# 기존 방식
old_evidence = await retrieve_evidence(metrics, test_session)
old_prompt = build_prompt(metrics, test_session, old_evidence)
old_result = invoke_claude(old_prompt)

# AgentCore 방식
new_result = invoke_agent(
    prompt=build_session_prompt(metrics, test_session),
    patient_id="test-001",
)

# 근거 수, 임상 키워드 포함 여부, 구조 완성도 비교
```

### 10.4 Policy 작동 확인

진단 단정 표현이 포함된 응답이 Policy에 의해 차단되는지 확인한다.

```python
# AgentCore가 "언어발달장애입니다" 같은 표현을 생성하면
# Cedar Policy가 차단하고 오류 이벤트를 발생시켜야 한다
```

---

## 11. 삭제 대상 코드

AgentCore 전환 완료 후 아래 파일/함수를 제거한다.

| 대상 | 이유 |
|---|---|
| `app/rag/rag_graph.py` | AgentCore가 에이전트 루프를 대체 |
| `app/rag/retriever.py` → `Retriever` 클래스 | Lambda 핸들러로 이식 완료 |
| `app/pipelines/bedrock_client.py` → `invoke_claude()` | `agentcore_client.invoke_agent()`로 대체 |
| `retrieve_evidence()` 호출부 (`report_pipeline.py`) | AgentCore 내부에서 tool로 처리 |

`retrieve_evidence()` 함수 자체는 Lambda 핸들러 내부에서 계속 사용하므로 로직은 유지한다.

---

## 12. 비용 가이드

### 컴포넌트별 단가

#### Claude 모델 (Amazon Bedrock)

| 모델 | 입력 | 출력 | 권장 용도 |
|---|---|---|---|
| Claude Haiku 4.5 | $1.00 / 1M 토큰 | $5.00 / 1M 토큰 | tool 호출 판단 + SOAP Note 생성 (기본값) |
| Claude Sonnet 4.6 | $3.00 / 1M 토큰 | $15.00 / 1M 토큰 | 복잡한 임상 케이스 (선택적) |

> `app/config.py`의 `bedrock_report_model_id`(현재 `claude-haiku-4-5-20251001-v1:0`)를 그대로 사용하면 추가 비용 변경 없음.

#### AgentCore 컴포넌트

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

#### Lambda (KURE-v1 검색)

| 항목 | 프리티어 | 초과 단가 |
|---|---|---|
| 요청 수 | 1,000,000건/월 무료 | $0.20 / 1M건 |
| 실행 시간 | 400,000 GB-초/월 무료 | $0.0000166667 / GB-초 |

**KURE-v1 (3 GB × ~10초 = 30 GB-초/건):**  
프리티어로 월 최대 **13,333건** 무료 처리 가능 → 현재 규모에서 Lambda 비용 **$0**.

### 월간 비용 시뮬레이션

| 규모 | Lambda | LLM (Haiku) | AgentCore | **합계** |
|---|---|---|---|---|
| 소규모 (100 세션/월) | $0 (프리티어) | ~$0.95 | ~$0.23 | **~$1.18** |
| 중규모 (500 세션/월) | $0 (프리티어) | ~$4.75 | ~$1.17 | **~$5.92** |
| 대규모 (2,000 세션/월) | $0 (프리티어) | ~$19.00 | ~$4.68 | **~$23.68** |
| 초대규모 (10,000 세션/월) | ~$4.00 | ~$95.00 | ~$23.40 | **~$122** |

> 위 수치는 Haiku 기준이며, 세션당 입력 3,500 토큰 + 출력 1,200 토큰, AgentCore 세션당 1분, tool 호출 3회 기준 추정치.

### 비용 최적화 전략

#### 1. Prompt Caching 활용
시스템 프롬프트와 임상 안전 지침은 세션 간 변하지 않으므로 Bedrock Prompt Caching을 적용한다.

```yaml
# agentcore-config.yaml
promptCache:
  enabled: true   # 시스템 프롬프트 캐시 → 입력 토큰 최대 90% 절감
```

#### 2. Haiku/Sonnet 혼용 (Tiered Model Strategy)
tool 호출 판단은 Haiku, 최종 SOAP Note 생성만 Sonnet을 선택적으로 사용해 비용과 품질을 균형 잡는다.

```yaml
# agentcore-config.yaml
model: us.anthropic.claude-haiku-4-5-20251001-v1:0   # tool 루프는 Haiku
finalizationModel: us.anthropic.claude-sonnet-4-6-v1:0  # 최종 생성은 Sonnet (선택)
```

#### 3. Lambda Provisioned Concurrency
cold start가 세션 응답 시간에 영향을 준다면 Provisioned Concurrency($7–15/월)를 고려한다.  
EventBridge 5분 워밍업(무료)으로 먼저 시도하고, 응답 시간 SLA가 엄격할 때만 적용한다.

#### 4. maxIterations 제한
`agentcore-config.yaml`의 `maxIterations: 5`가 tool 호출 최대 횟수를 제한한다.  
tool 1회 호출 = Lambda 1건 + 추가 입/출력 토큰이므로, 임계값을 필요 이상 높이지 않는다.

### 비용 모니터링

```bash
# AgentCore 일별 토큰 사용량 확인
aws cloudwatch get-metric-statistics \
  --namespace AWS/Bedrock \
  --metric-name InvocationInputTokens \
  --dimensions Name=AgentId,Value=utterai-soap-agent \
  --start-time 2026-06-01T00:00:00Z \
  --end-time 2026-06-30T00:00:00Z \
  --period 86400 \
  --statistics Sum
```

AWS Cost Explorer에서 `bedrock-agentcore` 서비스 태그로 필터링하면 컴포넌트별 비용을 분리해 확인할 수 있다.

> 상세 요금은 [AgentCore 요금 페이지](https://aws.amazon.com/bedrock/agentcore/pricing/) 및 [AWS Pricing Calculator](https://calculator.aws/pricing/2/home)에서 확인한다.

---

## 참고

- [ADR-001-agentic-rag.md](./ADR-001-agentic-rag.md)
- [Amazon Bedrock AgentCore 공식 문서](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [AgentCore Gateway Tool 등록 가이드](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)