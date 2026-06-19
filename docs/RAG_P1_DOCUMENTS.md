# RAG P1 문서 작업 기록

> 작성일: 2026-06-19  
> 대상 브랜치: feat/rag-p1-documents  
> 작업 범위: RAG 지식베이스 P1 우선순위 임상 가이드 4개 신규 작성

---

## 목차

1. [작업 배경 및 필요성](#1-작업-배경-및-필요성)
2. [P0와 P1의 차이](#2-p0와-p1의-차이)
3. [커버리지 공백 분석](#3-커버리지-공백-분석)
4. [문서별 상세 내용](#4-문서별-상세-내용)
   - 4-1. doc_fluency_guide — 유창성 장애 평가 및 중재 가이드
   - 4-2. doc_school_age_guide — 학령기 언어장애 임상 가이드
   - 4-3. doc_receptive_language_guide — 수용언어 평가 및 중재 가이드
   - 4-4. doc_goal_writing_guide — 임상 목표 작성 가이드
5. [DOC_METADATA 등록 내용](#5-doc_metadata-등록-내용)
6. [기대 효과](#6-기대-효과)
7. [참고문헌](#7-참고문헌)

---

## 1. 작업 배경 및 필요성

### UtterAI의 핵심 사용 시나리오

UtterAI는 언어재활사가 세션을 마친 후 SOAP Note 초안을 AI가 생성하도록 돕는 서비스입니다. SOAP Note의 품질은 RAG(Retrieval-Augmented Generation) 파이프라인이 얼마나 관련성 높은 임상 지식을 검색하느냐에 달려 있습니다.

RAG 파이프라인은 세션 데이터(측정 지표, 아동 연령, 임상 영역)를 받아 pgvector에서 관련 청크를 검색하고, 이를 Bedrock Claude에 컨텍스트로 전달합니다. 검색된 청크가 해당 임상 상황과 맞지 않으면 Claude는 근거 없이 답변을 생성합니다.

### 기존 지식베이스의 임상 영역 커버리지

1단계(코드 개선)와 2단계(P0 규칙 문서) 이후 지식베이스에 있는 임상 가이드는 다음과 같습니다.

| 문서 | 주요 커버 영역 | age_group |
|---|---|---|
| doc_language_sample_metrics | MLU, TTR, NDW, PCC 지표 해석 | preschool |
| doc_korean_morphosyntax | 형태통사 분석, 격조사·어미 | preschool |
| doc_adult_slp_guide | 실어증, 인지-의사소통, 마비말장애, CIU | adult |
| doc_child_slp_population | DLD, ASD, 조음·음운, 화용 | preschool |
| doc_child_assessment_tools | PRES, SELSI, REVT, U-TAP2, APAC 등 | preschool |

이 5개 문서를 분석하면 네 가지 주요 공백이 보입니다.

---

## 2. P0와 P1의 차이

| 구분 | P0 (2단계) | P1 (3단계) |
|---|---|---|
| 문서 유형 | `scoring_rule`, `safety_rule` | `clinical_guide` |
| 역할 | 계산 근거와 표현 안전 규칙 | 임상 영역 커버리지 확장 |
| 없으면 | 수치 해석 근거 없음, 단정 표현 생성 위험 | 해당 영역 질문에 빈 컨텍스트 전달 |
| 청크 크기 | 100~150자 (짧은 규칙 단위) | 300자 (clinical_guide 기본값) |

P1 문서가 없으면 "말더듬 아동 중재 방향을 알려주세요"라는 쿼리에 검색 결과가 0개이거나, 관련 없는 성인 실어증 청크가 반환됩니다.

---

## 3. 커버리지 공백 분석

### 공백 1: 유창성 장애 (Fluency Disorders) — 아동·성인 모두 미커버

기존 5개 문서 어디에도 말더듬(stuttering), 속화증(cluttering), 유창성 평가도구(P-FA-II), 중재 접근법(리드콤, 말더듬 수정법)이 체계적으로 다뤄지지 않습니다.

실제 임상에서 말더듬은 독립적인 주요 진단 범주입니다. 취학 전 아동 100명 중 약 5%가 말더듬을 경험하고, 그 중 약 65~80%가 자연회복하지만 나머지는 성인 말더듬으로 이어집니다(Yairi & Ambrose, 2013). 국내에서는 P-FA-II가 표준 평가도구로 사용됩니다.

**이 공백의 임상 영향**: "P-FA-II 결과 % SS 12%입니다"라는 입력에 RAG가 아무것도 검색하지 못하면, Claude는 %SS가 무엇인지, 어떤 심각도 기준을 적용해야 하는지, 아동인지 성인인지에 따라 중재 방향이 어떻게 다른지 알 수 없습니다.

### 공백 2: 학령기 아동 (School-age, 6~12세) — age_group 전혀 없음

기존 모든 가이드는 `age_group: preschool` 또는 `age_group: adult`입니다. 만 6~12세 학령기 아동은 preschool도 adult도 아닌데, 이 연령대를 위한 문서가 전혀 없습니다.

학령기는 언어가 학습의 도구로 전환되는 시기입니다. 취학 전에 해결되지 않은 DLD(발달성 언어장애)가 읽기 어려움, 작문 어려움, 학습부진으로 이어집니다. 국내에서는 LSSC(학령기 아동 언어 검사), KOLRA(읽기 검사)가 사용됩니다.

**이 공백의 임상 영향**: "초등학교 3학년 아동이 이야기를 구성하지 못합니다"라는 입력에 preschool 문서가 검색되어 MLU 중심의 영유아 중재 방향이 제시됩니다. LSSC, 음운 인식, 읽기 중재 관련 내용은 전혀 없습니다.

### 공백 3: 수용언어 임상 가이드 — 검사도구 안내만 있음

`doc_child_assessment_tools`에서 PRES와 REVT가 언급되지만, 이 문서의 목적은 검사도구 소개입니다. 수용언어 장애의 임상 특성, 평가 절차, 수용·표현 불일치 패턴 해석, 중재 원칙은 어디에도 없습니다.

수용언어 어려움은 표현언어 지연과 자주 공존하면서도 독립적으로 나타납니다. "이해는 하는데 말이 늦다"와 "말은 하는데 이해를 못 한다"는 완전히 다른 임상 프로파일이며, 중재 방향도 다릅니다.

**이 공백의 임상 영향**: "PRES 수용언어 점수가 표현언어 점수보다 훨씬 낮습니다"라는 입력에 수용·표현 불일치 패턴의 임상적 의미, 해석 방법, 중재 우선순위를 설명하는 청크가 없습니다.

### 공백 4: 임상 목표 작성 — clinical_task 태그만 있고 가이드 없음

1단계에서 `clinical_task: goal_writing` 메타데이터 필드를 추가했지만, 실제로 목표 작성 방법을 설명하는 문서가 없습니다. SOAP Note의 Plan 섹션은 단기·장기 목표를 포함해야 하는데, Claude가 목표 작성 형식과 원칙을 모르면 일관성 없는 목표를 생성합니다.

**이 공백의 임상 영향**: "중재 목표를 작성해주세요"라는 요청에 "언어 능력을 향상시킨다"처럼 측정 불가능하고 모호한 목표가 생성됩니다. SMART 원칙, 단서 수준, 정확도 기준 등이 포함된 구체적 목표를 작성하지 못합니다.

---

## 4. 문서별 상세 내용

### 4-1. `doc_fluency_guide` — 유창성 장애 평가 및 중재 가이드

**파일명**: `doc_fluency_guide__유창성장애_평가_및_중재_가이드.txt`  
**source_type**: `clinical_guide`  
**age_group**: `all` (아동·성인 모두 포함)  
**language_area**: `fluency`, `pragmatics`  
**metric**: `percent_ss`, `sld_ratio`  
**clinical_task**: `assessment`, `report_generation`, `goal_writing`, `intervention`  
**assessment_tool**: `P-FA-II`, `OASES`

#### 왜 만들었나

말더듬은 조음장애나 언어발달지연과는 완전히 다른 임상 접근이 필요합니다. 평가도구(P-FA-II), 핵심 지표(%SS), 비유창성 유형 분류, 연령별 중재 접근법이 모두 독립적인 전문 지식입니다. 이 정보 없이는 Claude가 유창성 세션 데이터를 해석하거나 SOAP Note를 작성할 수 없습니다.

#### 무엇이 담겨 있나

**정상 비유창성 vs 비정상 비유창성 (SLD) 구별 기준**

임상에서 가장 중요한 첫 번째 판단입니다. 아동의 발달 과정에서 나타나는 정상 비유창성과 말더듬을 구별하지 못하면 과잉 진단 또는 과소 진단이 발생합니다.

| 유형 | 특징 | 임상 의미 |
|---|---|---|
| 정상 비유창성 | 단어 전체 반복, 구 반복, 삽입어 — 긴장 없음 | 발달적으로 허용 범위 |
| SLD (말더듬 유사 비유창성) | 부분 단어 반복, 음소 연장, 막힘, 신체 긴장 | 임상적 주의 필요 |

기준: SLD가 100음절당 3회 이상, 신체 긴장·회피 행동 동반 시 말더듬으로 판단.

**P-FA-II 구조와 핵심 지표**

국내 표준 유창성 평가도구인 P-FA-II의 구성과 산출 지표를 설명합니다.

- `% SS` (Percentage of Stuttered Syllables): 말더듬 음절 비율
  - 계산: 말더듬 음절 수 ÷ 총 음절 수 × 100
  - 심각도 기준: 0~3%(정상), 4~5%(약함), 6~9%(중간), 10~16%(심함), 17% 이상(매우 심함)
- 비유창성 유형 코드: PartRep(부분 단어 반복), Pro(연장), Blo(막힘), Int(삽입어), Rev(수정)
- 부수 행동 점수: 신체 긴장, 눈 깜빡임, 회피 행동

**아동 말더듬 자연회복 예측 인자**

중재 여부를 결정하는 핵심 임상 판단입니다. 자연회복 가능성이 높으면 경과 관찰을, 낮으면 즉시 중재를 시작합니다.

자연회복 가능성을 낮추는 위험 인자: 남아, 발병 후 6개월 이상 경과, 가족력, 부분 단어 반복과 막힘 비율 높음, 신체 긴장·회피 행동 동반.

**연령별 중재 접근법 (아동)**

- 리드콤 프로그램(Lidcombe Program): 만 6세 미만 아동 대상 부모 중심 행동 치료. 부모가 가정에서 유창한 발화에 언어적 강화("잘 말했어요")를 제공. Jones 외(2005) RCT에서 효과 확인.
- 파린 PCI(Palin Parent-Child Interaction): 아동-부모 상호작용을 수정하는 간접 중재. 부모의 말 속도, 질문 빈도, 반응 시간 조정.
- 간접 중재: 아동에게 직접 말더듬을 다루지 않고 말하기 환경 조성.

**성인 중재 접근법**

- 말더듬 수정법(Van Riper, 1973): 확인 → 탈감각화 → 수정(취소·당김·준비) → 안정화. 말더듬 자체보다 말더듬에 대한 반응 변화 목표.
- 유창성 형성법: 부드럽게 시작하기(Soft Onset), 말 속도 줄이기, 연속 발성. 말하는 방식 자체를 재구조화.
- ACT(Acceptance and Commitment Therapy): 말더듬 수용, 심리적 유연성, 가치 중심 삶.

**SOAP Note 섹션별 작성 포인트**: S(주관적 보고: 회피 상황·불안), O(%SS 수치·유형 분포·부수 행동), A(심각도 등급·위험 인자), P(중재 방향·부모 교육·회기 계획)

---

### 4-2. `doc_school_age_guide` — 학령기 언어장애 임상 가이드

**파일명**: `doc_school_age_guide__학령기_언어장애_임상_가이드.txt`  
**source_type**: `clinical_guide`  
**age_group**: `school_age` (만 6~12세, 신규 age_group 값)  
**language_area**: `expressive_language`, `receptive_language`, `narrative_discourse`, `phonology`  
**metric**: `mlu_morpheme`, `ndw`  
**clinical_task**: `assessment`, `report_generation`, `goal_writing`, `intervention`  
**assessment_tool**: `LSSC`, `KOLRA`, `KOPLAC`

#### 왜 만들었나

기존 문서의 `preschool`은 만 0~6세 취학 전 아동을 대상으로 합니다. 학령기(초등학교 1~6학년, 만 7~12세)는 완전히 다른 임상 패러다임이 필요합니다.

학령기에서 언어는 더 이상 발달 목표 자체가 아니라 **학습의 도구**입니다. DLD가 지속되면 읽기, 쓰기, 수업 이해, 또래 관계 전반에 영향을 미칩니다. 평가도구도 PRES/SELSI가 아닌 LSSC, KOLRA가 주로 사용되며, 중재 목표도 이야기 구성, 어휘 확장, 음운 인식, 읽기 해독 중심으로 바뀝니다.

이 문서는 `school_age`라는 신규 `age_group` 값을 도입합니다. 이로써 학령기 아동 세션 데이터가 들어왔을 때 preschool 가이드가 검색되는 문제가 해결됩니다.

#### 무엇이 담겨 있나

**취학 전 vs 학령기 언어재활 차이**

| 구분 | 취학 전 | 학령기 |
|---|---|---|
| 언어의 역할 | 일상 의사소통 발달 | 학습 도구 |
| 핵심 영역 | 어휘, 구문, 화용, 음운 | 읽기, 쓰기, 담화, 학업 어휘 |
| 주요 지표 | MLU, NDW, TTR, PCC | 읽기 정확도·유창도, 이야기 구조, 작문 |
| 협력 대상 | 보호자 | 보호자 + 담임교사 + 특수교사 |

**발달성 언어장애(DLD)의 학령기 양상**

취학 전에 진단된 DLD가 어떻게 학령기 어려움으로 이어지는지 설명합니다.

구어 영역: 복잡한 구문 이해 오류, 이야기 구성 능력 저하, 주제 유지 어려움.

읽기 영역: 해독(decoding) 어려움, 읽기 유창성 부족, 해독은 되나 이해가 안 됨.

쓰기 영역: 철자 오류 지속, 단순하고 반복적인 문장 구조, 작문 계획·조직화 어려움.

**언어기반 학습장애(LBLD)와 음운 처리 3요소**

읽기 어려움의 언어학적 기반을 설명합니다.

1. 음운 인식(Phonological Awareness): 음절·음소 수준 소리 조작 능력
2. 음운 작업기억(Phonological Working Memory): 청각 정보 단기 저장 — 비단어 따라 말하기로 측정
3. 빠른 자동화 이름대기(RAN, Rapid Automatized Naming): 글자·숫자·색 이름 대기 — 읽기 유창성의 강력한 예측 변수

이 세 가지가 학령기 읽기장애(난독증 포함)의 핵심 기저 요인입니다.

**학령기 평가 도구**

- LSSC(학령기 아동 언어 검사, 만 7~12세): 어휘, 문법, 화용, 듣기 이해, 읽기
- KOLRA(읽기 검사, 초등 1~6학년): 해독, 읽기 유창성, 읽기 이해, 음운 인식, RAN
- KOPLAC: 학령기 다차원 언어 평가 프로토콜
- 이야기 평가: 그림 자극 이야기 구성, 이야기 5요소 분석
- 비단어 따라말하기: 음운 작업기억

**이야기 평가 분석 항목**

이야기 5요소(배경-계기-시도-결과-반응), 접속사 종류와 빈도(그리고/그래서/그런데/왜냐하면), 내적 상태어 사용(생각·느낌·믿음), 결속 장치 오류.

**읽기 평가 분리 원칙**

해독과 읽기 이해를 반드시 분리 평가합니다. 해독은 되나 이해가 안 되는 경우(단순읽기이해장애)와 해독 자체가 어려운 경우(난독증형 읽기장애)는 중재 방향이 다릅니다.

**중재 방향**

- 이야기 중재: 이야기 문법 도식(story grammar) 5요소 명시적 교수, 이야기 지도 시각 자료
- 어휘 중재: Tier 2 학업 어휘 중심(비교하다, 분석하다, 예측하다), 의미지도, 어원 분석
- 음운 인식 중재: 음절/음소 분리·합성, GPC 체계적 교수 — 메타분석에서 읽기 해독 효과 확인(Ehri 외, 2001)
- 학교 연계: 담임교사 교육, IEP 연계, 학습 자료 조정

---

### 4-3. `doc_receptive_language_guide` — 수용언어 평가 및 중재 가이드

**파일명**: `doc_receptive_language_guide__수용언어_평가_및_중재_가이드.txt`  
**source_type**: `clinical_guide`  
**age_group**: `preschool`  
**language_area**: `receptive_language`  
**metric**: (없음 — 수용언어는 표준화 점수 중심)  
**clinical_task**: `assessment`, `report_generation`, `goal_writing`, `intervention`  
**assessment_tool**: `PRES`, `REVT`, `SELSI`

#### 왜 만들었나

`doc_child_assessment_tools`에서 PRES와 REVT가 언급되지만 이는 "이런 검사 도구가 있다"는 소개입니다. "수용언어 점수가 표현언어 점수보다 낮을 때 어떻게 해석하는가", "지시 따르기 단계를 어떻게 평가하는가", "수용언어 중재 원칙은 무엇인가"에 해당하는 내용이 없습니다.

임상에서 수용언어 평가는 표현언어 평가와 반드시 함께 이루어지며, 두 영역의 불일치 패턴이 중재 방향을 결정합니다. 이 패턴 해석 지식이 없으면 SOAP Note A 섹션(Assessment)이 단순히 "수용언어 지연"이라는 결론만 제시하게 됩니다.

#### 무엇이 담겨 있나

**수용언어 4개 하위 구성 요소**

수용언어를 단일 능력으로 보지 않고 4가지 하위 능력으로 분리합니다.

1. **음운 지각**: 음소·음절 수준 소리 변별. "발" vs "팔" 구별. 어려움 시 언어발달지연 초기 징후.
2. **어휘 이해**: 단어 의미 이해. 사물 지시, 동사 이해, 속성어(크다/작다), 공간 관계어(위/아래/앞/뒤).
3. **구문 이해**: 문장 구조와 조사·어미 이해. 격조사 이해(토끼가 곰을 vs 곰이 토끼를), 부정문, 시제, 복문, 수동태.
4. **담화 이해**: 연결된 발화·이야기 수준 이해. 단계적 지시 따르기, 이야기 듣고 질문 답하기, 추론적 이해.

이 4단계 구분이 중요한 이유: "이해를 못 한다"고 보고된 아동이 어휘 이해는 정상이나 복문 구문 이해가 어려운 경우, 중재는 복문 구조에 집중해야 하고 어휘 교육은 우선순위가 아닙니다.

**수용·표현 불일치 패턴 3가지**

| 패턴 | 특성 | 원인 예시 | 임상 방향 |
|---|---|---|---|
| 수용 > 표현 | 이해하지만 말이 늦음 | 말 실행증, 선택적 함구증 | 표현 산출에 집중 |
| 수용·표현 모두 지연 | 이해·표현 모두 어려움 | DLD, ASD, 지적장애 | 수용 수준에 맞춰 중재 언어 조정 |
| 표현 > 수용 | 말은 하지만 이해 어려움 | ASD 에코랄리아, APD | 수용 중재 우선 |

패턴 2에서 중재자가 아동 수용언어 수준보다 높은 언어를 쓰면 아동이 따라오지 못합니다. "수용·표현 모두 지연"인 경우 중재 언어도 수용 등가월령에 맞춰야 한다는 원칙이 이 문서에 명시됩니다.

**평가 도구 세부 설명**

- SELSI(0~36개월): 부모 보고 기반, 수용·표현 각 56문항, 영역별 등가월령·LQ
- PRES(만 2~6세 5개월): 수용·표현 분리 채점이 핵심. 의미·문법·화용 영역 구분. 불일치 패턴 파악에 최적.
- REVT(만 2세 6개월~성인): 수용어휘(그림 선택)와 표현어휘(이름 대기) 분리. 어휘 등가연령 산출.

**비표준화 평가: 지시 따르기 단계**

표준화 검사 외 비구조화 상황에서 지시 따르기 능력을 평가하는 방법입니다.
- 1단계: "공 줘" (단일 조건)
- 2단계: "빨간 공을 상자 안에 넣어요" (2개 조건)
- 3단계: "파란 블록을 상자에서 꺼내서 바닥에 놓아요" (3개 조건)

단계별 정확도가 단기 목표 수준을 결정합니다.

**중재 원칙과 기법**

- 원칙: 아동 수용언어 수준보다 한 단계 높은 언어로 자극 제시
- 비언어적 단서 점진적 소거: 실물·그림·제스처 → 언어만
- 어휘 이해: 시각적 페어링, 범주 분류, 8~12회 반복 노출
- 구문 이해: 수동 조작 과제(그림 선택, 사물 이동), 단계적 복잡성 증가
- 이야기 이해: 사전 스키마 활성화, 이야기 중 중간 점검

**보호자 교육 핵심 내용**: 짧고 단순하게 말하기, 천천히 말하기, 비언어적 단서 동반, 이해 확인 방법("알겠어?" → "다시 말해볼래?"), 일상 반복 노출.

---

### 4-4. `doc_goal_writing_guide` — 임상 목표 작성 가이드

**파일명**: `doc_goal_writing_guide__임상_목표_작성_가이드.txt`  
**source_type**: `clinical_guide`  
**age_group**: `all`  
**language_area**: `clinical_documentation`, `functional_communication`  
**metric**: (없음)  
**clinical_task**: `goal_writing`, `report_generation`  
**assessment_tool**: (없음)

#### 왜 만들었나

SOAP Note의 Plan 섹션은 단기·장기 목표를 포함합니다. Claude가 이 섹션을 생성할 때 목표 작성 원칙을 모르면 "언어 능력을 향상시킨다"처럼 측정 불가능하고 모호한 목표가 생성됩니다.

좋은 목표는 **SMART 원칙**과 **ICF 프레임워크**를 따릅니다. 이 두 가지가 담긴 가이드가 RAG에 있으면, "목표를 작성해주세요"라는 요청에 Claude가 구체적이고 측정 가능한 목표를 생성하게 됩니다.

또한 이 문서는 `clinical_task: goal_writing` 필터와 연동되어, SOAP Plan 생성 요청에서만 집중적으로 검색됩니다.

#### 무엇이 담겨 있나

**SMART 원칙 상세 설명**

| 요소 | 의미 | 잘못된 예 | 올바른 예 |
|---|---|---|---|
| S (Specific) | 무엇을 어떻게 할 것인가 | "언어 능력 향상" | "격조사 포함 2어절 발화 산출" |
| M (Measurable) | 수치·관찰 기준 | "잘 말한다" | "10시도 중 8회(80%) 정확" |
| A (Achievable) | 현 수준에서 도달 가능 | 현재 0%인데 100% 목표 | 현재 50%이면 70~80% 목표 |
| R (Relevant) | 일상 기능에 의미 있음 | 치료실 과제만 | 가정·학교 일반화 포함 |
| T (Time-bound) | 기간 명시 | 기간 없음 | "3개월 이내", "10회기 이내" |

**ICF 3수준 목표**

WHO ICF 프레임워크에 따라 목표를 세 수준으로 분류합니다.

- 신체 기능/구조 수준: MLU-m 3.5 이상 발화 산출, 격조사 정확도 80%
- 활동 수준: 치료사와의 2~3어절 발화로 요구 표현하기
- 참여 수준: 가정에서 부모에게 원하는 것 문장으로 말하기, 또래와 놀이 중 의사소통 유지하기

기능적 목표(참여 수준)를 최소 1개 포함하는 것이 권장됩니다. 치료실 수행이 일상으로 일반화되었는지를 참여 수준 목표로 추적합니다.

**목표 구성 5요소**

```
[누가] + [어떤 상황/맥락에서] + [무엇을] + [어떤 단서로] + [어느 수준까지]
```

예시: "아동은 치료사의 그림 자극 제시 조건에서 격조사(주격/목적격)를 포함한 2어절 이상의 발화를 최소 단서로 10회 시도 중 8회(80%) 이상 정확하게 산출한다"

**단서 수준 4단계**

| 단서 수준 | 설명 | 기술 방법 |
|---|---|---|
| 독립적 | 단서 없이 수행 | "독립적으로" |
| 최소 단서 | 한 가지 간단한 단서 | "구어 단서 1회로", "첫 음소 단서로" |
| 중간 단서 | 의미·구문·모델링 | "의미 단서 제공 후", "선택지 2개 중" |
| 최대 단서 | 완전한 모델 후 반복 | "모델링 후 즉각 모방" |

치료 진전은 동일 행동을 더 낮은 단서 수준에서 수행하게 되는 것으로 측정합니다.

**연령·영역별 목표 예시 전체**

문서에는 다음 8가지 상황별 단기/장기 목표 예시가 포함됩니다:
- 영유아/취학전 표현언어 (사물+동사 2어절, 격조사 산출)
- 취학전 음운 (어두 초성 자음 정확도)
- 아동 수용언어 (공간 관계어, 격조사 역전 문장)
- 학령기 이야기 (5요소 이야기 구성)
- 학령기 읽기 (CVC 해독, 음절 분리)
- 성인 실어증 (이름대기, %CIU, 일상 의사소통)
- 성인 유창성 (말더듬 수정 기법 적용, Soft Onset)

**SOAP Plan 섹션 전체 구조**

목표 외에 Plan 섹션이 포함해야 할 요소: 중재 접근법·기법, 회기 빈도·기간, 가정 프로그램(보호자 실시 활동), 협력 계획(교사·특수교육·의료진), 재평가 계획.

**피해야 할 목표 작성 실수 목록**: 구체성 없는 목표, 기준 없는 목표, 측정 불가 기술, 단서 수준 불명확, 진단 확정 표현 포함.

**목표 작성 체크리스트 8개 항목**: 누가/상황/행동/단서 수준/달성 기준/기간/진단 표현 없음/장기 목표 연결 여부.

---

## 5. DOC_METADATA 등록 내용

`scripts/ingest_rag_docs.py`의 `DOC_METADATA`에 4개 문서가 등록됩니다.

```python
"doc_fluency_guide": {
    "age_group": "all",
    "language_area": ["fluency", "pragmatics"],
    "metric": ["percent_ss", "sld_ratio"],
    "clinical_task": ["assessment", "report_generation", "goal_writing", "intervention"],
    "assessment_tool": ["P-FA-II", "OASES"],
},
"doc_school_age_guide": {
    "age_group": "school_age",
    "language_area": ["expressive_language", "receptive_language", "narrative_discourse", "phonology"],
    "metric": ["mlu_morpheme", "ndw"],
    "clinical_task": ["assessment", "report_generation", "goal_writing", "intervention"],
    "assessment_tool": ["LSSC", "KOLRA", "KOPLAC"],
},
"doc_receptive_language_guide": {
    "age_group": "preschool",
    "language_area": ["receptive_language"],
    "metric": [],
    "clinical_task": ["assessment", "report_generation", "goal_writing", "intervention"],
    "assessment_tool": ["PRES", "REVT", "SELSI"],
},
"doc_goal_writing_guide": {
    "age_group": "all",
    "language_area": ["clinical_documentation", "functional_communication"],
    "metric": [],
    "clinical_task": ["goal_writing", "report_generation"],
    "assessment_tool": [],
},
```

`school_age`는 이번에 처음 도입된 `age_group` 값입니다. `age_group` 필드는 자유 문자열이므로 DB 마이그레이션 없이 추가 가능합니다.

---

## 6. 기대 효과

### 유창성 문서 추가 후

| 이전 | 이후 |
|---|---|
| "P-FA-II %SS 12%입니다" → 빈 컨텍스트 | %SS 심각도 기준(심함 등급) 청크 검색 |
| 리드콤/말더듬 수정법 관련 질문 → 빈 결과 | 연령에 맞는 중재 접근법 청크 검색 |
| 비유창성 유형 분류 불가 | PartRep/Pro/Blo 코드와 SLD/OD 구분 청크 검색 |

### 학령기 문서 추가 후

| 이전 | 이후 |
|---|---|
| "초등 3학년 이야기 구성 어려움" → preschool MLU 청크 검색 | school_age 가이드·이야기 5요소 청크 검색 |
| LSSC/KOLRA 결과 해석 근거 없음 | 학령기 평가 프로파일 및 해석 기준 청크 검색 |
| 음운 처리 3요소 모름 | RAN·음운 인식·작업기억 관련 청크 검색 |

### 수용언어 문서 추가 후

| 이전 | 이후 |
|---|---|
| "PRES 수용 < 표현" → 해석 근거 없음 | 수용·표현 불일치 패턴 해석 청크 검색 |
| 지시 따르기 단계 목표 설정 불가 | 1/2/3단계 지시 기준 및 목표 예시 청크 검색 |
| 수용언어 중재 원칙 모름 | 단서 소거·어휘 페어링·구문 수동조작 청크 검색 |

### 목표 작성 문서 추가 후

| 이전 | 이후 |
|---|---|
| "목표를 작성해주세요" → "언어 능력을 향상시킨다" | SMART 구조 + 단서 수준 + 정확도 기준 포함 목표 |
| ICF 참여 수준 목표 없음 | 가정·학교 일반화 목표 포함 |
| Plan 섹션 구조 불일치 | 목표 + 중재법 + 빈도 + 가정 프로그램 구조화 |

---

## 7. 참고문헌

Yairi, E., & Ambrose, N. G. (2013). Epidemiology of stuttering: 21st century advances. *Journal of Fluency Disorders*, 38(2), 66–87.

Jones, M., Onslow, M., Packman, A., Williams, S., Ormond, T., Schwarz, I., & Gebski, V. (2005). Randomised controlled trial of the Lidcombe programme of early stuttering intervention. *BMJ*, 331(7518), 659–661.

Van Riper, C. (1973). *The treatment of stuttering*. Englewood Cliffs, NJ: Prentice-Hall.

Bishop, D. V. M., Snowling, M. J., Thompson, P. A., Greenhalgh, T., & CATALISE-2 Consortium (2017). Phase 2 of CATALISE: A multinational and multidisciplinary Delphi consensus study of problems with language development. *Journal of Child Psychology and Psychiatry*, 58(10), 1087–1100.

Ehri, L. C., Nunes, S. R., Willows, D. M., Schuster, B. V., Yaghoub-Zadeh, Z., & Shanahan, T. (2001). Phonemic awareness instruction helps children learn to read: Evidence from the National Reading Panel's meta-analysis. *Reading Research Quarterly*, 36(3), 250–287.

WHO (2001). *International classification of functioning, disability and health: ICF*. Geneva: World Health Organization.

배소영, 이승환, 한재순 (2000). *언어발달장애*. 서울: 시그마프레스.

김영태, 성태제, 이윤경 (2003). *취학전 아동의 수용언어 및 표현언어 발달 척도(PRES)*. 서울: 서울장애인종합복지관.

김영태, 홍경훈, 김경희, 장혜성, 이주연 (2009). *수용·표현 어휘력 검사(REVT)*. 서울: 서울장애인종합복지관.

이효주, 최소영, 이윤경 (2015). *학령기 아동 언어 검사(LSSC)*. 서울: 학지사.

배소영, 김미배, 윤효진, 장승민 (2015). *한국어 읽기 검사(KOLRA)*. 서울: 학지사.

이상희, 신문자, 이은주 (2010). *파라다이스 유창성 검사 II(P-FA-II)*. 서울: 파라다이스복지재단.