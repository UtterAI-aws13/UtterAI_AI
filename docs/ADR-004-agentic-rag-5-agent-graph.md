# ADR-004: 리포트 생성 Agent를 Strands Graph 기반 5-Agent로 전환 (ADR-002 supersede)

| 항목 | 내용 |
|---|---|
| **상태** | Accepted |
| **작성일** | 2026-07-03 |
| **결정자** | UtterAI AI 팀 |
| **supersedes** | [ADR-002-agentcore-harness-vs-strands.md](./ADR-002-agentcore-harness-vs-strands.md) (리포트 생성 agent 범위에 한함) |
| **관련 문서** | `01_production_5_agent_agentic_rag_design.md` (Implementation Contract) |
| **관련 파일** | `app/pipelines/agentcore_client.py`, `app/pipelines/report_pipeline.py`, `app/agents/report_generation/` (신규) |

---

## 1. 배경 및 문제 정의

ADR-002는 리포트 생성 agent에 대해 "에이전트 루프를 코드로 소유할 것인가 vs AWS에 위임할 것인가"라는 질문에 **AgentCore Managed Harness 위임**으로 답했다. 근거는 크게 두 가지였다.

1. 에피소딕 Memory로 환자 이전 세션의 MLU 변화 추이를 자동 반영해야 한다.
2. Cedar Policy로 "진단 단정 금지"를 인프라 레벨에서 강제해야 한다.

`01_production_5_agent_agentic_rag_design.md`(이하 "5-Agent 설계서")는 이 결정을 다음 근거로 뒤집는다.

- ADR-002가 근거로 든 "환자 정량 지표를 Memory에 반영"은 애초에 **금지 대상**이다. 설계서 §0.2, §7.2는 MLU/TTR/NDW 등 정량 지표를 RDS deterministic query로만 조회하도록 못박고 있고, AgentCore Memory를 source of truth로 쓰는 것을 명시적으로 금지한다.
- ADR-002가 "인프라 레벨 강제"라 표현한 Cedar Policy는, 설계서 §22.5 기준으로 **자연어 출력 안전을 전부 보장하지 못하는 보조 수단**이다. 실제 안전 강제는 deterministic validator + Quality Assurance Agent라는 코드 레벨 게이트가 맡아야 한다.
- ADR-002 자체가 §5 "재검토 조건"에서 이미 예고했다: "tool 호출 순서나 조건을 동적으로 제어해야 하는 복잡한 임상 오케스트레이션이 필요할 때 Strands SDK 전환을 재검토한다." 5-Agent 설계서가 요구하는 흐름(근거 부족 시 재검색 cycle, 품질 실패 시 재작성 cycle, evidence critic의 독립 승인 게이트)이 정확히 그 조건이다.
- ADR-003(인사이트맵)이 이미 지적했듯, 코드 레벨로 루프를 소유하면서도 로컬 실행·디버깅이 가능한 구조가 임상 안전성 검증(golden test, 재현 가능한 회귀 테스트)에 더 적합하다.

따라서 본 ADR은 **리포트 생성 agent에 한해** ADR-002를 supersede한다. `report_editing_chatbot`, `insight_map`의 Strands SDK 사용(ADR-003)에는 영향이 없다.

---

## 2. 결정

### 2.1 리포트 생성 agent loop는 Strands Graph로 코드가 소유한다

```text
[ADR-002 (기존)]
app/pipelines/agentcore_client.py
  client.invoke_agent_runtime(...)   # 루프는 AgentCore Managed Harness가 실행
                                      # 앱은 완성된 JSON 텍스트만 파싱

[ADR-004 (본 결정)]
app/agents/report_generation/graph.py
  Strands Graph:
    LOAD_CONTEXT (deterministic)
    → Clinical Context Agent
    → Evidence Research Agent
    → Evidence Critic Agent
    → Clinical Report Agent
    → DETERMINISTIC_VALIDATION (deterministic)
    → Quality Assurance Agent
    → FINAL_VALIDATION (deterministic)
    → SAVE_DRAFT
  전체 Graph를 AgentCore Runtime에 배포하되, Runtime은 실행 환경일 뿐
  orchestration(조건 분기·재시도·상태)은 앱 코드(Strands Graph)가 소유한다.
```

### 2.2 5개 전문 Agent + 3개 deterministic node로 책임을 분리한다

Managed Harness의 단일 범용 agent(`search_evidence` tool 1개, 조건부 재시도 없음)를 다음으로 대체한다.

| 구성 요소 | 유형 | 역할 |
|---|---|---|
| LOAD_CONTEXT | deterministic | 세션/히스토리 조회, 권한 검증, 중복 실행 방지 |
| Clinical Context Agent | Agent | 세션+히스토리 → 핵심 clinical finding 구조화 |
| Evidence Research Agent | Agent | 문헌 근거 검색·query expansion·재검색 |
| Evidence Critic Agent | Agent | 검색 근거 독립 평가 (ACCEPT/RESEARCH_MORE/HUMAN_REVIEW) |
| Clinical Report Agent | Agent | 승인된 근거로 SOAP 초안 + claim trace 생성 |
| DETERMINISTIC_VALIDATION | deterministic | schema/citation/권한/injection 규칙 검사 |
| Quality Assurance Agent | Agent | 독립 최종 심사 (PASS/RESEARCH_MORE/REWRITE/HUMAN_REVIEW/FAIL) |
| FINAL_VALIDATION, SAVE_DRAFT | deterministic | 최종 저장 게이트 |

Research Agent와 Critic Agent, Clinical Report Agent와 QA Agent는 각각 서로 다른 Agent 객체다 (생성자와 검수자를 분리해 self-review 편향을 막는다).

### 2.3 AgentCore Memory는 patient 정량 지표의 source of truth로 쓰지 않는다

ADR-002가 채택 근거로 들었던 "Memory 기반 MLU 추이 자동 반영"은 폐기한다. `LOAD_CONTEXT` 노드가 `patient_session_summaries`/`session_metrics` 등 RDS 테이블을 deterministic query로 직접 조회해 `patient_history`를 구성한다. AgentCore Memory를 쓰더라도 용도는 치료사 표현 선호·이전 수정 패턴 같은 비정량 정보로 한정한다.

### 2.4 Cedar Policy는 tool access 제어로 역할을 축소한다

ADR-002는 Cedar를 "진단 단정 금지"를 강제하는 안전 계층으로 취급했다. 본 ADR은 Cedar/Gateway 정책의 역할을 tool 호출 권한 제어로 한정하고, 임상 표현 안전은 다음 다층 구조로 코드 레벨에서 강제한다.

```text
Agent system prompt
+ Pydantic structured output (허용/금지 표현이 스키마로 강제됨)
+ DETERMINISTIC_VALIDATION (rule-based 금지 표현 검사)
+ Quality Assurance Agent (독립 최종 심사, safety score == 1.00 게이트)
+ (선택) Bedrock Guardrails
+ 치료사 최종 검토
```

---

## 3. 검토한 옵션

### Option A: ADR-002 유지 (Managed Harness, 현행)

**장점**: 이미 동작 중, `agentcore_client.py` 단순.
**단점**: tool 1개(`search_evidence`)만 존재해 근거 recall/critic/QA 단계가 없음. 재검색·재작성 cycle을 만들 수 없음(루프를 AWS가 소유하므로). 저장 전 validator가 report-generation 경로에 연결되어 있지 않음(코드 조사로 확인된 기존 결함). Memory가 정량 지표 source of truth로 쓰이는 구조라 금지 조건과 충돌.

### Option B: Strands 단일 Agent + Tool 7개 (01_agentic_rag_report_generation.md 안)

**장점**: ADR-002보다는 통제 가능하지만 구현 범위가 5-Agent안보다 작음.
**단점**: 근거 검색과 근거 평가를 같은 Agent(자기 자신)가 수행하면 self-review 편향이 생긴다. 5-Agent 설계서는 이 문제를 Evidence Research Agent와 Evidence Critic Agent 분리로 해결하는데, 단일 Agent 구조에서는 이 분리가 불가능하다.

### Option C: Strands Graph + 5-Agent (채택)

**장점**: 아래 §4.

**단점**: 구현 범위가 가장 크다 (Phase 1~6, 5개 Agent + 3개 deterministic node + Graph routing + retry budget). Agent 호출 횟수가 늘어 latency/비용이 Option A/B 대비 증가한다 (§7 참고).

---

## 4. 결정 근거

| 판단 기준 | ADR-002 (Managed Harness) | 본 ADR (Strands Graph 5-Agent) |
|---|---|---|
| tool 호출 순서 제어 | ❌ AWS 위임, `maxIterations`로만 상한 제한 | ✅ Graph edge로 명시적 정의 |
| 근거 부족 시 재검색 | ❌ 불가 (단일 tool, 단일 호출 루프) | ✅ Evidence Critic → RESEARCH_MORE cycle (최대 3회) |
| 생성-검수 분리 | ❌ 동일 실행 흐름 내 self-check 없음 | ✅ Research/Critic, Report/QA를 별도 Agent로 분리 |
| 환자 정량 지표 출처 | ⚠️ Memory 기반 자동 주입 (금지 대상과 충돌) | ✅ RDS deterministic query |
| 임상 안전 강제 | Cedar Policy (인프라 레벨, 자연어 검증 불완전) | deterministic validator + QA Agent + Cedar(tool 제어로 축소) 다층 방어 |
| 로컬 실행/디버깅 | ❌ 불가 | ✅ 필수 요건 (동일 Graph를 local/AgentCore 양쪽에서 실행) |
| 저장 전 validator 연결 | ⚠️ 기존 코드 조사 결과 report-generation 경로에 미연결 | ✅ DETERMINISTIC_VALIDATION + QA PASS gate 통과해야 SAVE_DRAFT |
| retry budget 소진 시 처리 | 정의 없음 | HUMAN_REVIEW로 안전하게 격하 (자동 승인 금지) |

Memory와 Cedar Policy를 근거로 들었던 ADR-002의 판단은, 그 두 근거 자체가 이번 설계서에서 금지·축소 대상이 되면서 더 이상 유효하지 않다. 반면 ADR-002가 "필수 요건 아님"으로 판단했던 로컬 디버깅과 루프 제어는, 임상 안전 검증(golden regression)과 재검색/재작성 cycle 요구가 생기면서 핵심 요건으로 바뀌었다.

---

## 5. 결과 및 트레이드오프

### 긍정적 결과

- 근거 부족/품질 미달 시 자동 재시도·재작성이 가능해지고, budget 소진 시 자동 승인 대신 HUMAN_REVIEW로 격하된다.
- 문헌 근거와 환자 근거가 `evidence_trace`에서 namespace 분리되어 저장된다.
- A/P 섹션 핵심 claim마다 evidence trace가 강제되어(§11.6) 무근거 문장을 QA 단계에서 걸러낼 수 있다.
- 동일 Graph를 로컬(`--fixture`)과 AgentCore Runtime 양쪽에서 실행할 수 있어 golden regression을 CI에 넣을 수 있다.

### 부정적 결과 및 완화 방안

| 리스크 | 완화 방안 |
|---|---|
| Agent 호출 횟수 증가로 latency/비용 상승 | `MAX_TOTAL_MODEL_CALLS`(기본 20)로 상한, Agent별 모델 성격을 역할에 맞게 분리(§15) — 예: Critic/QA는 저비용·저온도 모델 사용 검토 |
| 구현/테스트 범위 대폭 증가 | Phase 1~6 단계별 구현, Phase마다 산출물 확인 후 다음 Phase 진행 |
| Memory/Cedar를 안전장치로 쓰던 기존 가정 폐기에 따른 회귀 위험 | deterministic validator + QA PASS gate가 Cedar의 빈 자리를 코드 레벨로 대체, golden set(§24.3, 15개 케이스)으로 회귀 검증 |
| AWS provider가 AgentCore Gateway 신규 리소스만 지원(provider 6.x) | Infra 쪽 IaC를 5.x 스택과 분리된 별도 스택으로 격리 (`05-agentcore`, 별도 커밋에서 이미 처리) |

### 재검토 조건

다음 상황이 발생하면 본 ADR을 재검토한다.

- 5-Agent 구조의 latency/비용이 실제 운영에서 감당 불가능한 수준으로 확인될 때 (Agent 수 축소는 임의로 하지 않고 ADR을 먼저 갱신한다 — 설계서 §0.2)
- AgentCore Memory/Cedar Policy가 향후 "정량 지표 source of truth 아님", "tool 제어 전용" 제약 없이도 임상 안전을 보장할 수 있는 수준으로 성숙할 때
- Strands Graph의 cycle/retry 기능이 실제 운영 요구(예: 근거 재검색 3회 초과 필요)를 충족하지 못한다고 확인될 때

---

## 6. 적용 범위

- **적용됨**: 리포트 생성 agent (`app/agents/report_generation/`, `report_pipeline.py`가 호출하는 경로).
- **영향 없음**: `report_editing_chatbot`(ADR-003이 별도로 다룸), `insight_map`(ADR-003).
- 기존 `app/pipelines/agentcore_client.py`(Managed Harness 호출)와 `app/rag/rag_graph.py`(LangGraph 기반 구현)는 5-Agent Graph로 대체되며, 마이그레이션 완료 후 제거 대상이다. 제거 시점은 Phase 5(Runtime/API) 완료 이후로 별도 확인한다.

---

## 7. 관련 문서

- [ADR-001-agentic-rag.md](./ADR-001-agentic-rag.md) — AgentCore 채택 결정 (Runtime을 실행 환경으로 쓰는 부분은 유지)
- [ADR-002-agentcore-harness-vs-strands.md](./ADR-002-agentcore-harness-vs-strands.md) — 본 ADR이 리포트 생성 agent 범위에서 supersede
- [ADR-003-insight-map-agent-runtime.md](./ADR-003-insight-map-agent-runtime.md) — 인사이트맵 agent는 본 ADR의 영향을 받지 않음
- `01_production_5_agent_agentic_rag_design.md` — 본 ADR이 구현하는 Implementation Contract 전문
