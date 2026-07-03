# ADR-002: AgentCore Managed Harness vs Strands Agents SDK

| 항목 | 내용 |
|---|---|
| **상태** | Accepted (리포트 생성 agent 범위는 [ADR-004](./ADR-004-agentic-rag-5-agent-graph.md)로 supersede됨) |
| **작성일** | 2026-06-30 |
| **결정자** | UtterAI AI 팀 |
| **관련 ADR** | [ADR-001-agentic-rag.md](./ADR-001-agentic-rag.md), [ADR-003-insight-map-agent-runtime.md](./ADR-003-insight-map-agent-runtime.md) (예외), [ADR-004-agentic-rag-5-agent-graph.md](./ADR-004-agentic-rag-5-agent-graph.md) (리포트 생성 agent supersede) |
| **관련 파일** | `app/pipelines/agentcore_client.py` |

> **2026-07-03 갱신**: 리포트 생성 agent에 대한 이 문서의 결정(Managed Harness 채택)은 [ADR-004](./ADR-004-agentic-rag-5-agent-graph.md)로 대체되었다. `report_editing_chatbot`, `insight_map`(ADR-003)에는 여전히 이 문서가 유효하다.

---

## 1. 배경 및 문제 정의

ADR-001에서 Amazon Bedrock AgentCore를 에이전트 런타임으로 채택했다.  
이후 AgentCore 위에서 에이전트 로직을 **어떻게 구현할 것인가**라는 세부 결정이 필요했다.

AWS가 제공하는 두 가지 방식이 있다.

- **Strands Agents SDK**: 에이전트 루프를 Python 코드로 직접 작성하는 오픈소스 라이브러리
- **AgentCore Managed Harness**: 에이전트 루프를 AWS가 관리하고, 앱은 boto3로 결과만 수신

---

## 2. 두 방식의 차이

두 방식은 **레이어가 다르다**. Strands SDK는 에이전트 로직을 코드로 정의하는 도구이고, Managed Harness는 그 로직을 실행하는 인프라다. 서로 대체할 수도 있고, Strands로 작성한 에이전트를 AgentCore에 배포하는 조합도 가능하다.

이번 결정의 핵심 질문은:  
**"에이전트 루프를 코드로 소유할 것인가 vs AWS에 위임할 것인가"**

```
[Strands SDK 방식]
app/
  └─ agent.py
        @tool
        def search_evidence(query: str): ...

        agent = Agent(tools=[search_evidence])
        result = agent("세션 데이터 분석해줘")   # 루프를 앱 내에서 실행

[Managed Harness 방식 — 우리 선택]
app/
  └─ agentcore_client.py
        client.invoke_agent(inputText=prompt)    # 루프는 AgentCore가 실행
                                                  # 앱은 완성된 결과만 수신
```

---

## 3. 검토한 옵션

### Option 1: Strands Agents SDK

Python 코드로 `@tool`을 선언하고 에이전트 루프를 직접 작성한다.  
에이전트는 EKS 또는 Lambda 위에서 실행한다.

**장점**
- 에이전트 루프를 완전히 제어할 수 있음 (tool 호출 순서 강제, 조건부 중단 등)
- 로컬에서 `python agent.py`로 즉시 실행 및 breakpoint 디버깅 가능
- 오픈소스라 내부 동작을 코드 레벨로 확인 가능
- AWS 외 환경에서도 실행 가능 (이식성)

**단점**
- Memory, Cedar Policy, Gateway를 직접 구현해야 함
- 에이전트 실행 인프라(스케일링, 재시도, 오류 복구)를 직접 관리해야 함
- 임상 안전 정책을 앱 코드로 강제하면 우회 가능성이 생김

---

### Option 2: AgentCore Managed Harness (선택)

에이전트 루프, Memory, Cedar Policy, Gateway를 AWS가 관리한다.  
앱 코드는 boto3로 `invoke_agent()`를 호출하고 완성된 결과만 수신한다.

**장점**
- Memory(환자 세션 에피소딕), Cedar Policy(임상 안전 규칙), CloudWatch 트레이스가 코드 없이 제공됨
- 에이전트 실행 인프라를 AWS가 관리 — 스케일링, 오류 복구 포함
- Cedar Policy는 에이전트 실행 레벨에서 강제되므로 앱 코드로 우회 불가

**단점**
- 에이전트 루프 내부를 직접 볼 수 없음 (CloudWatch 트레이스로만 관찰)
- 로컬 디버깅 불가 — 반드시 AWS 환경 배포 후 확인해야 함
- AgentCore 신생 서비스로 Terraform provider 미지원, 레퍼런스 부족
- AWS 벤더 의존도 심화

---

## 4. 결정: Option 2 — AgentCore Managed Harness

### 근거

| 기능 | Strands SDK | Managed Harness |
|---|---|---|
| 에이전트 루프 제어 | ✅ 완전 제어 | ❌ AWS 위임 |
| 로컬 디버깅 | ✅ 가능 | ❌ 불가 |
| 세션 Memory | ❌ 직접 구현 | ✅ 기본 제공 |
| Cedar Policy 강제 | ❌ 직접 구현 | ✅ 기본 제공 |
| CloudWatch 트레이스 | ❌ 직접 구축 | ✅ 자동 통합 |
| 임상 안전 우회 방지 | ❌ 앱 레벨만 | ✅ 인프라 레벨 강제 |
| 인프라 관리 | ❌ 직접 | ✅ AWS 관리 |

**Memory와 Policy가 결정적이었다.**

에피소딕 Memory는 환자 이전 세션의 MLU 변화 추이를 현재 세션에 자동 반영하는 데 필요하다. Strands SDK로 구현하면 별도 DB 스키마, 조회/주입 로직, 세션 관리 코드가 수반된다.

Cedar Policy의 "진단 단정 금지" 규칙은 의료 도메인 안전 요건이다. 앱 레벨 가드레일은 코드 변경으로 우회될 수 있지만, Managed Harness의 Cedar Policy는 에이전트 실행 레벨에서 강제되어 우회가 불가능하다.

Strands SDK의 주요 장점인 **루프 제어**와 **로컬 디버깅**은 현재 단계에서 필수 요건이 아니다. 에이전트가 `search_evidence` tool을 최대 5회 호출하는 단순한 루프이며, 복잡한 오케스트레이션 커스터마이징이 불필요하다.

---

## 5. 결과 및 트레이드오프

### 긍정적 결과

- `agentcore_client.py`가 70줄 미만으로 단순하게 유지됨
- Memory, Policy, 트레이스 구현 공수 제거
- "진단 단정 금지" 정책이 인프라 레벨에서 강제됨

### 부정적 결과 및 완화 방안

| 리스크 | 완화 방안 |
|---|---|
| 로컬 디버깅 불가 | CloudWatch 트레이스 + `tool_use` 로그 패턴으로 검증 |
| 에이전트 루프 불투명 | `maxIterations: 5` 설정으로 동작 범위 제한 |
| 벤더 락인 | Lambda 내부 도메인 로직(KURE-v1, pgvector)을 AgentCore와 완전 분리 유지 |
| AgentCore 미성숙 | Terraform 대신 AWS CLI로 AgentCore 리소스 관리 (provider 지원 시 전환) |

### 재검토 조건

다음 상황이 발생하면 Strands SDK 전환을 재검토한다.

- tool 호출 순서나 조건을 동적으로 제어해야 하는 복잡한 임상 오케스트레이션이 필요할 때
- AgentCore 서비스 장애로 인한 가용성 문제가 반복될 때
- 로컬 에이전트 실행이 개발 생산성에 병목이 될 때

---

## 6. 관련 문서

- [ADR-001-agentic-rag.md](./ADR-001-agentic-rag.md) — AgentCore 채택 결정
- [AGENTIC_RAG_GUIDE.md](./AGENTIC_RAG_GUIDE.md) — 전체 구현 가이드