# ADR-003: 인사이트맵 보조 Agent는 Strands SDK로 유지 (ADR-002 예외)

| 항목 | 내용 |
|---|---|
| **상태** | Proposed |
| **작성일** | 2026-07-01 |
| **결정자** | UtterAI AI 팀 |
| **관련 ADR** | [ADR-002-agentcore-harness-vs-strands.md](./ADR-002-agentcore-harness-vs-strands.md) |
| **관련 문서** | `03-온톨로지맵-별도창-설계서.md` |
| **관련 파일** | `app/agents/insight_map/` (신규), `app/agents/report_editing_chatbot/` |

---

## 1. 배경 및 문제 정의

ADR-002는 "에이전트 루프를 코드로 소유할 것인가 vs AWS에 위임할 것인가"라는 질문에 대해 **AgentCore Managed Harness를 기본 런타임으로 채택**했다. 이 결정은 Agentic RAG의 임상 리포트 생성 agent — 진단 단정 금지 같은 Cedar Policy 강제, 환자 세션 간 에피소딕 Memory가 필요한 agent — 를 전제로 내려졌다.

한편 "인사이트용 온톨로지맵" 설계서는 신규 `insight_query_resolver_agent`(자연어 검색어 → concept 후보 변환)와 `insight_explainer_agent`(노드/경로 설명 생성)를 도입하면서, 설계서 14절에서 다음을 명시적으로 금지한다.

> Managed Harness를 온톨로지맵 핵심 구현으로 사용하지 말 것.

즉 설계서의 요구사항이 ADR-002의 기본 방향과 문면상 충돌한다. 이 문서는 그 충돌을 해소하고, 인사이트맵 보조 agent 두 개에 한해 **Strands SDK를 유지하는 것이 ADR-002 위반이 아니라 의도된 예외**임을 기록한다.

---

## 2. 인사이트맵 agent가 ADR-002의 전제와 다른 점

| 판단 기준 (ADR-002 결정 근거) | Agentic RAG 리포트 생성 agent | 인사이트맵 보조 agent |
|---|---|---|
| 에피소딕 Memory 필요성 | 필요 (환자 세션 간 MLU 추이를 agent가 기억해야 함) | 불필요 — 환자 히스토리는 `patient_metric_trends`/`soap_case_indexes` 테이블에 구조화 저장되어 있고, agent는 매 호출마다 Graph API가 조회해준 데이터만 받아 요약함 |
| Cedar Policy(임상 안전 우회 방지) 필요성 | 필요 (진단 단정 금지) | 낮음 — concept resolve와 노드 설명은 리포트를 직접 생성하거나 임상 판단을 내리지 않음 (설계서 2절: "온톨로지맵은 리포트를 직접 생성하지 않는다") |
| 에이전트 루프 복잡도 | tool을 조건부·반복 호출하는 오케스트레이션 | 단일 tool 호출 1~2회로 끝나는 단순 매핑/요약 (`search_ontology_concepts`, `search_synonyms`) |
| 로컬 실행·테스트 요구 | 필수 아님 | 설계서 13절 완료 기준에 "Strands agent가 local 실행 가능해야 한다"가 명시됨 — Managed Harness는 로컬 디버깅 불가(ADR-002 3절 단점)라 이 요구를 충족 못함 |
| 메인 구현체 여부 | agent 자체가 리포트 생성의 핵심 | 설계서 1절: "온톨로지맵의 핵심은 agent가 아니라 그래프 데이터 모델 + API + UI"이며 agent는 보조 해석기일 뿐 |

ADR-002가 Managed Harness를 선택한 핵심 근거(Memory, Cedar Policy)가 인사이트맵 보조 agent에는 적용되지 않는다. 반대로 ADR-002가 Strands SDK의 단점으로 꼽은 "로컬 디버깅 불가"는 인사이트맵에서는 오히려 로컬 실행이 요구사항이므로, Strands 쪽이 더 적합하다.

---

## 3. 결정

인사이트맵의 `insight_query_resolver_agent`와 `insight_explainer_agent`는 **ADR-002의 적용 범위에서 제외**하고, Strands Agents SDK로 구현한다.

- 이 두 agent는 그래프 저장소 역할을 하지 않는다 (설계서 14절). 순수하게 "자연어 → concept 후보", "경로 → 설명 텍스트" 변환만 수행하는 상태 없는(stateless) 유틸리티에 가깝다.
- AgentCore Runtime 배포는 선택 사항으로 남긴다. 배포하더라도 Strands로 작성한 코드를 AgentCore 위에 얹는 것(ADR-002가 언급한 "조합 가능" 옵션)이지, Managed Harness가 루프를 대신 실행하는 방식으로 전환하지 않는다.
- ADR-002의 원래 결정(Agentic RAG 리포트 생성 agent는 Managed Harness)은 그대로 유지된다. 본 ADR은 그 결정을 뒤집지 않고, 적용 범위를 좁힌다.

### 참고: 기존 `report_editing_chatbot`과의 관계

현재 `app/agents/report_editing_chatbot/agent.py`도 Strands SDK로 구현되어 있어, ADR-002가 "Accepted"된 이후에도 아직 Managed Harness로 전환되지 않은 상태다. 이는 본 ADR의 결정 대상이 아니며, 별도로 팀이 전환 여부·시점을 논의해야 한다. 다만 인사이트맵 agent를 이 폴더와 동일한 Strands 패턴(`agent.py` + `prompts.py` + `tools.py`)으로 구현하면, 향후 `report_editing_chatbot`을 Managed Harness로 옮기는 논의와 인사이트맵 agent의 논의를 독립적으로 진행할 수 있다.

---

## 4. 재검토 조건

다음 상황이 발생하면 인사이트맵 agent의 Managed Harness 전환을 재검토한다.

- 인사이트맵 agent가 환자별 검색 히스토리를 세션 간 기억해야 하는 요구가 생길 때 (에피소딕 Memory 필요)
- concept 설명·추천에도 임상 안전 가드레일(예: 특정 진단명 단정 금지)이 필요해질 때
- 단순 tool 1~2회 호출을 넘어서는 복잡한 조건부 오케스트레이션이 필요해질 때

---

## 5. 관련 문서

- [ADR-002-agentcore-harness-vs-strands.md](./ADR-002-agentcore-harness-vs-strands.md) — Managed Harness 기본 채택 결정
- `03-온톨로지맵-별도창-설계서.md` — 인사이트맵 전체 설계서