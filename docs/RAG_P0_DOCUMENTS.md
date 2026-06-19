# RAG P0 문서 작업 기록

> 작성일: 2026-06-19  
> 대상 브랜치: feat/rag-p0-documents  
> 작업 범위: RAG 지식베이스 P0 우선순위 규칙 문서 5개 신규 작성

---

## 목차

1. [작업 배경 및 필요성](#1-작업-배경-및-필요성)
2. [P0 문서란 무엇인가](#2-p0-문서란-무엇인가)
3. [문서별 상세 내용](#3-문서별-상세-내용)
   - 3-1. doc_metric_exception_rule — 발화 계산 공통 제외 기준
   - 3-2. doc_metric_mlu_korean_rule — 한국어 MLU 계산 규칙
   - 3-3. doc_metric_pcc_korean_rule — 한국어 PCC 계산 규칙
   - 3-4. doc_metric_ciu_korean_rule — CIU 계산 규칙
   - 3-5. doc_report_safety_rule — 임상 리포트 단정 표현 금지 규칙
4. [source_type 설계](#4-source_type-설계)
5. [DOC_METADATA 등록 내용](#5-doc_metadata-등록-내용)
6. [기대 효과](#6-기대-효과)
7. [참고문헌](#7-참고문헌)

---

## 1. 작업 배경 및 필요성

### 문제 정의

RAG 지식베이스에 임상 해석 가이드(clinical_guide)와 학술 논문(research_paper)만 있으면, Bedrock Claude는 다음 두 가지 상황에서 근거 없이 답변을 생성하게 됩니다.

**상황 1: 수치를 받아도 계산 기준을 모른다**

세션 분석 결과로 `mlu_morpheme: 2.3`이 들어왔을 때, Claude는 이 수치가 어떻게 계산된 건지 모릅니다.

- 반복 발화를 포함했는가? 제외했는가?
- 형태소 단위인가, 낱말 단위인가?
- 간투사("음", "어")는 어떻게 처리됐는가?

계산 기준이 다르면 같은 수치도 해석이 달라집니다. 예를 들어 반복 발화를 포함하고 계산한 MLU 2.3과 제외하고 계산한 MLU 2.3은 임상적 의미가 다릅니다. Claude가 이 기준 없이 "MLU 2.3은 낮습니다"라고만 답하면 임상적으로 불완전한 리포트가 됩니다.

**상황 2: 리포트 생성 시 단정적 표현을 쓴다**

근거 문헌에 "MLU가 낮으면 언어발달지연 가능성이 있다"는 내용이 있으면, Claude는 이를 "MLU 2.3으로 언어발달지연이 확인된다"처럼 단정적으로 변환할 수 있습니다. 임상에서 AI가 생성한 리포트에 진단 확정 문구가 포함되면 법적·윤리적 문제가 생깁니다.

### 기존 문서의 한계

1단계에서 구성된 5개 임상 가이드는 "무엇이 MLU인가", "어떻게 해석하는가"를 설명합니다. 그러나 "어떻게 계산하는가", "무엇을 제외하는가", "어떤 표현은 쓰면 안 되는가"에 해당하는 **운영 규칙**은 포함하지 않습니다.

ASHA(2016)의 EBP(Evidence-Based Practice) 모델은 임상 의사결정이 최신 연구근거 + 임상 전문성 + 내담자 선호의 통합이어야 한다고 설명합니다. RAG도 마찬가지로 "연구 근거 문서"만으로는 부족하고, 임상 운영 규칙 문서가 함께 있어야 합니다.

---

## 2. P0 문서란 무엇인가

P0는 "없으면 다른 문서를 아무리 잘 넣어도 품질 보장이 안 되는" 최우선 순위 문서입니다.

| 우선순위 | 기준 | P0 해당 여부 |
|---|---|---|
| P0 | 없으면 LLM이 계산 근거 없이 답하거나 위험한 표현을 생성함 | ✅ |
| P1 | 핵심 임상 영역 커버 (아동/성인 대상군별 가이드) | — |
| P2 | 추가 영역 보강 (학령기, AAC 등) | — |
| P3 | 완성도 향상 (사례 라이브러리, 평가셋 등) | — |

P0 문서는 두 가지 신규 `source_type`을 사용합니다.

- **`scoring_rule`**: 지표 계산 규칙·포함/제외 기준. chunk_size=150자 (짧은 규칙 단위로 독립 저장)
- **`safety_rule`**: 생성 표현 제한 규칙. chunk_size=100자 (금지/허용 표현이 섞이지 않도록 매우 작게)

---

## 3. 문서별 상세 내용

### 3-1. `doc_metric_exception_rule` — 발화 계산 공통 제외 기준

**파일명**: `doc_metric_exception_rule__발화_계산_공통_제외_기준.txt`  
**source_type**: `scoring_rule`  
**age_group**: `all`  
**language_area**: `expressive_language`, `vocabulary`, `phonology`, `narrative_discourse`, `fluency`  
**metric**: `mlu_morpheme`, `ttr`, `ndw`, `pcc`, `ciu_count`  
**clinical_task**: `assessment`

#### 왜 만들었나

MLU, TTR, NDW, PCC, CIU는 각각 별도 문서로 계산 규칙을 설명하지만, 모든 지표에 공통으로 적용되는 제외 기준은 어디에도 명시되어 있지 않습니다. 예를 들어 "반복 발화를 제외한다"는 원칙은 MLU에도, TTR에도, PCC에도 동일하게 적용됩니다. 이를 각 지표 문서마다 반복 기술하는 것보다 공통 규칙으로 분리하는 것이 일관성 유지에 유리합니다.

또한 RAG 검색 시 "간투사는 어떻게 처리하나요?"라는 질문에 특정 지표 문서가 아닌 이 공통 규칙 문서가 검색되어야 합니다.

#### 무엇이 담겨 있나

| 제외 유형 | 정의 | 판단 기준 |
|---|---|---|
| 불명료 발화 | 전사 불가능한 발화 | 전체의 50% 이상 불명료 시 발화 전체 제외 |
| 반복 발화 | 즉각 반복 | 최초 1회만 산입 |
| 자기수정 | false start, revision | 최종 완성 발화만 산입 |
| 간투사 | 음, 어, 아, 저기, 있잖아 등 | 의미 없이 독립 사용된 경우만 제외 |
| 모방 발화 | 즉각 모방 | 지연 모방은 문맥 판단 |
| 반향어 | ASD 아동의 즉각 반향어 | 기능적 반향어는 임상 판단 |
| 노래·암기 발화 | 동요, 구호, 인사말 공식 | 자발적 언어 산출이 아닌 경우 |

분석 대상 발화 수 기준(최소 50~100개)과 보고서 기재 형식도 포함합니다.

#### 근거 문헌

- Brown(1973)이 제안한 MLU 계산 원칙이 이 문서의 이론적 기반입니다. Brown은 즉각 모방, 반복, 관용적 표현을 MLU 계산에서 제외할 것을 최초로 명시했습니다.
- Miller(1981)는 이를 임상 언어표본분석 절차로 확장했습니다.
- SALT 매뉴얼(Miller & Iglesias, 2012)은 자기수정(revision), false start를 제외하는 전사 규칙을 표준화했습니다.
- 이윤경(2003)은 이 원칙을 한국어 아동 언어표본분석에 적용한 국내 대표 연구입니다.

---

### 3-2. `doc_metric_mlu_korean_rule` — 한국어 MLU 계산 규칙

**파일명**: `doc_metric_mlu_korean_rule__한국어_MLU_계산_규칙.txt`  
**source_type**: `scoring_rule`  
**age_group**: `preschool`  
**language_area**: `expressive_language`, `morphosyntax`  
**metric**: `mlu_morpheme`, `llu_morpheme`  
**clinical_task**: `assessment`, `report_generation`  
**assessment_tool**: `K-ALAS`

#### 왜 만들었나

MLU는 영어권에서 Brown(1973)이 고안했고, 영어는 어절·낱말·형태소가 대부분 일치합니다("the dog runs" = 3낱말 = 약 3형태소). 그러나 한국어는 교착어(agglutinative language)라 어절 하나에 어휘 정보와 문법 정보가 결합됩니다.

"토끼가" = 어절 1개 = 낱말 1개 = 형태소 2개(토끼 + 가)

단위를 무엇으로 선택하느냐에 따라 MLU 수치 자체가 달라집니다. Claude가 "MLU 2.3"이라는 수치를 받았을 때, 이것이 형태소 단위인지 낱말 단위인지 알 수 없으면 해석이 어렵습니다. 이 문서는 한국어 임상에서 어떤 단위를 권장하는지, 각 단위의 계산 방법이 무엇인지, 어떤 형태소를 포함·제외하는지를 규정합니다.

#### 무엇이 담겨 있나

**단위 선택 기준**

| 단위 | 기호 | 예시("토끼가 당근을 먹어요") | 권장 여부 |
|---|---|---|---|
| 형태소 | MLU-m | 토끼+가+당근+을+먹+어+요 = 7 | ✅ 권장 |
| 낱말 | MLU-w | 토끼, 당근, 먹다 = 3 | 보조 지표 |
| 어절 | MLU-e | 토끼가, 당근을, 먹어요 = 3 | 보조 지표 |

MLU-m이 권장되는 이유: 한국어 아동의 문법형태소(조사, 어미) 발달을 가장 민감하게 반영합니다. "토끼 먹어"(조사 누락, 형태소 4개)와 "토끼가 당근을 먹어요"(조사 포함, 형태소 7개)의 차이가 MLU-m에서 명확하게 드러납니다.

**형태소 분절 기준**

포함: 어간, 어미(종결·연결·전성), 격조사, 보조사, 의존명사(것·때), 파생접사

예시 분절:
- "공원에서 놀고 싶어요" → 공원+에서+놀+고 싶+어+요 = 6형태소
- "엄마가 밥을 줬어요" → 엄마+가+밥+을+주+었+어+요 = 8형태소

예외 처리: 복합어("학교", "가방"), 보조용언("-고 싶-"), 합성어 처리 기준을 명시하고 임상에서 일관 적용해야 함을 설명합니다.

**연령별 MLU-m 참고 기준** (추세 파악용, 단일 진단 기준 아님)

| 연령 | 평균 범위 | 주의 기준 |
|---|---|---|
| 만 2세 | 1.5~2.0 | 1.5 미만 |
| 만 3세 | 2.5~3.5 | 2.0 미만 |
| 만 4세 | 3.0~4.5 | 2.5 미만 |
| 만 5세 | 3.5~5.5 | 3.0 미만 |

해석 시 주의사항: MLU 단독 진단 불가, 치료사 발화 유형의 영향, 단일 회기보다 변화 추이 중심 해석, K-ALAS 자동 분석과 전문가 수동 분석 간 차이 가능성.

#### 근거 문헌

- Brown(1973): MLU 개념 정립 및 영어 계산 원칙 제안
- 이윤경(2003), 이윤경·이효주(2003): 한국어 아동 MLU 발달 연구, 연령별 참고 기준
- 이지연 외(2023): K-ALAS 신뢰도 연구. 전문가 수동 분석과 r=.972~1.000 상관 확인. K-ALAS 기반 형태소 분석 기준의 신뢰도 근거.
- 배소영 외(2000): 한국어 아동 언어표본분석 절차의 국내 표준화 근거

---

### 3-3. `doc_metric_pcc_korean_rule` — 한국어 PCC 계산 규칙

**파일명**: `doc_metric_pcc_korean_rule__한국어_PCC_계산_규칙.txt`  
**source_type**: `scoring_rule`  
**age_group**: `preschool`  
**language_area**: `phonology`  
**metric**: `pcc`  
**clinical_task**: `assessment`, `report_generation`  
**assessment_tool**: `U-TAP2`, `APAC`

#### 왜 만들었나

PCC(Percent Consonants Correct, 자음정확도)는 목표 자음 중 정확하게 산출된 비율입니다. 기존 임상 가이드 문서(`doc_language_sample_metrics`, `doc_child_assessment_tools`)에서 PCC가 무엇인지, U-TAP2/APAC 검사 도구가 무엇인지는 설명하지만, 다음 내용은 없습니다.

- 한국어 자음 목록은 무엇인가 (19개, 파열음/파찰음/마찰음/비음/유음)
- 초성과 종성을 모두 포함하는가
- 모음은 어떻게 처리하는가 (PCC는 자음만)
- 불명료 자음 위치는 어떻게 처리하는가
- 대치·생략·왜곡의 구체적 한국어 예시는 무엇인가
- 자발화 PCC와 검사 PCC는 왜 다를 수 있는가

RAG가 "PCC 65%입니다"라는 입력을 받고 해석하려면, 이 수치가 어떤 기준으로 계산됐는지 알아야 합니다. 특히 초성만 계산했는지 초성+종성 모두 계산했는지에 따라 같은 발화라도 PCC 수치가 달라집니다.

#### 무엇이 담겨 있나

**한국어 자음 19개 분류**

| 분류 | 자음 |
|---|---|
| 파열음 | ㅂ, ㅍ, ㅃ, ㄷ, ㅌ, ㄸ, ㄱ, ㅋ, ㄲ |
| 파찰음 | ㅈ, ㅊ, ㅉ |
| 마찰음 | ㅅ, ㅆ, ㅎ |
| 비음 | ㅁ, ㄴ, ㅇ |
| 유음 | ㄹ |

**포함/제외 기준**

- 포함: 초성(어두·어중)과 종성(받침) 모두 포함
- 제외: 모음(PCC는 자음만), 불명료 발화 전체, 반복·모방 발화(공통 제외 기준 준용)

계산 예시:
- "밥" = 초성 ㅂ + 종성 ㅂ = 목표 자음 2개
- "사과" = 초성 ㅅ + 초성 ㄱ = 목표 자음 2개 (모음 ㅏ, ㅘ는 제외)

**오류 유형 분류**

| 유형 | 정의 | 한국어 예시 |
|---|---|---|
| 대치(Substitution) | 다른 자음으로 바꿔 산출 | /ㅅ/→/ㄷ/ ("사탕"→"다탕") |
| 생략(Omission) | 자음을 산출하지 않음 | 종성 /ㅂ/ 생략 ("밥"→"바") |
| 왜곡(Distortion) | 부정확하게 산출 | 치간음화, 설측음화 |

**한국어 주요 음운변동 패턴**

어말 자음 생략, 파열음화, 전설음화, 경음화 오류, 기음 오류 등 임상에서 자주 관찰되는 패턴과 검사도구 연계를 설명합니다.

**중증도 참고 기준** (영어권 기준, 한국어 규준은 U-TAP2/APAC 사용)

| PCC | 중증도 |
|---|---|
| 85% 이상 | 경미하거나 정상 |
| 65~84% | 경도~중등도 |
| 50~64% | 중등도~심도 |
| 50% 미만 | 심도 |

#### 근거 문헌

- Shriberg & Kwiatkowski(1982): PCC 지표 최초 제안. 목표 자음 대비 정확 산출 비율로 조음 정확도를 정량화하는 방법을 확립했습니다.
- 김민정 외(2007): U-TAP2 표준화 연구. 한국 아동 616명 대상 자음정확도 규준 자료.
- 하지완 외(2019): APAC 연구. 음운변동 분석과 PCC 계산 기준의 국내 임상 적용 근거.
- 2024년 연구: 한국어 말소리 자동분석도구(KSAT)와 임상가 수동분석 비교 결과, 오류패턴분석 일치도 93.63% 보고.

---

### 3-4. `doc_metric_ciu_korean_rule` — CIU 계산 규칙

**파일명**: `doc_metric_ciu_korean_rule__CIU_계산_규칙.txt`  
**source_type**: `scoring_rule`  
**age_group**: `adult`  
**language_area**: `narrative_discourse`, `functional_communication`  
**metric**: `ciu_count`, `ciu_ratio`, `ciu_per_minute`  
**clinical_task**: `assessment`, `report_generation`  
**assessment_tool**: `AphasiaBank`

#### 왜 만들었나

CIU(Correct Information Unit)는 성인 실어증 및 인지-의사소통 장애 평가의 핵심 담화 분석 지표입니다. 기존 `doc_adult_slp_guide`에서 CIU가 무엇인지, %CIU와 CIU/min이 무엇인지는 설명하지만, 다음은 설명하지 않습니다.

- 어떤 낱말을 CIU로 인정하는 정확한 3가지 조건
- 한국어 어절 단위로 CIU를 계산할 때의 처리 방법
- 착어(paraphasia) 발화를 CIU로 인정하는지 여부
- 침묵 구간을 발화 시간에 포함하는지 여부

특히 한국어는 조사가 어절에 붙어 있어 "어떤 단위로 낱말을 세는가"가 %CIU 수치에 영향을 줍니다. "여자가"를 1낱말로 처리할지, "여자"와 "가"를 2형태소로 분리할지에 따라 분모가 달라집니다.

#### 무엇이 담겨 있나

**CIU 인정 3조건**

1. 명료성(Intelligibility): 청취자가 해당 낱말을 명확하게 알아들을 수 있을 것
2. 정보성(Informativeness): 주제나 과제에 대한 새로운 정보를 전달할 것
3. 맥락 적절성(Contextual Accuracy): 대화 주제 또는 과제에 적합한 내용일 것

세 조건을 모두 충족하는 낱말만 CIU로 계산합니다.

**제외 대상 목록**

반복 낱말, 간투사·머뭇거림("음", "어"), 과제 무관 발화, 불명료 낱말, 착어(의미착어·음운착어)

**%CIU 계산 예시**

정상 발화 예시:
- "여자가 물이 넘치고 있어요. 아이가 의자에 올라가 있고요." → CIU 8개, 총 낱말 8개 → %CIU = 100%

중증 실어증 발화 예시:
- "저기... 어... 가방... 아니 그게... 물... 그거..." → CIU 1개("물"), 총 낱말 2개 → %CIU = 50%

**CIU/min 계산**

CIU/min = (총 CIU 수 ÷ 발화 시간(초)) × 60

침묵 구간 처리 기준(5초 이상 침묵 제외 여부)을 임상 전 확정하고 보고서에 명시해야 합니다.

**한국어 어절 단위 처리 권장**

"여자가", "물이", "넘치고"를 각각 1낱말로 처리합니다. 어절 단위를 사용하는 이유: 형태소 단위 분리 시 분석이 복잡해지고, 영어권 CIU 기준과의 비교가 어려워지며, 임상에서 분석자 간 일치도가 낮아집니다.

**해석 기준**

%CIU 참고 (영어권 정상 성인 기준, 한국어 규준 연구 필요):
- 정상 성인: 약 85~98%
- 경도 실어증: 약 65~84%
- 중등도 실어증: 약 40~64%
- 중증 실어증: 40% 미만

한국어 성인 %CIU 절대 규준이 부족하므로, 동일 과제·동일 분석 기준으로 치료 전후 변화를 비교하는 방식이 권장됩니다.

#### 근거 문헌

- Nicholas & Brookshire(1993): CIU 지표 최초 제안 논문. CIU의 3조건(명료성·정보성·맥락 적절성)과 %CIU, CIU/min 계산 방법을 확립했습니다. Journal of Speech and Hearing Research 게재.
- Kong(2009): 광동어 실어증 화자에게 CIU를 적용한 연구. 영어 이외 언어에서 CIU 적용 가능성과 단위 선택 문제를 다룹니다. 한국어 적용 기준 설계의 참고 근거.
- AphasiaBank(MacWhinney 외): 표준화된 담화 프로토콜과 Main Concept Analysis, CIU 자동 분석 도구를 제공하는 데이터베이스. CIU 분석 과제 선택의 국제 표준.

---

### 3-5. `doc_report_safety_rule` — 임상 리포트 단정 표현 금지 규칙

**파일명**: `doc_report_safety_rule__임상_리포트_단정_표현_금지_규칙.txt`  
**source_type**: `safety_rule`  
**age_group**: `all`  
**language_area**: `clinical_documentation`  
**metric**: (없음)  
**clinical_task**: `report_generation`

#### 왜 만들었나

이 문서는 품질 문제가 아닌 **안전(safety) 문제**입니다.

ASHA(2016)의 언어재활사 업무 범위에 따르면, 장애 진단과 임상 판단은 자격을 갖춘 언어재활사만 할 수 있습니다. AI가 생성한 리포트에 "언어발달지연이다", "실어증이 확인된다" 같은 진단 확정 문구가 포함될 경우, 이는 무면허 진단으로 해석될 수 있는 법적·윤리적 위험을 내포합니다.

또한 대한언어재활사협회 윤리강령은 근거 기반 서비스 제공 원칙을 명시하고 있으며, AI 생성 리포트가 검토 없이 내담자에게 전달되는 것을 방지하는 절차가 필요합니다.

이 문서를 RAG에 포함하면, 리포트 생성 쿼리가 들어왔을 때 Claude가 이 규칙 청크를 검색하여 표현 제한을 자동으로 적용하게 됩니다.

#### 무엇이 담겨 있나

**절대 사용 금지 표현 카테고리**

| 카테고리 | 금지 예시 | 이유 |
|---|---|---|
| 진단 확정 | "~장애가 있다", "~장애로 진단된다" | AI는 진단 권한이 없음 |
| 수치 기반 단정 | "MLU 2.3으로 언어발달지연이 확인된다" | 단일 수치로 장애 확정 불가 |
| 예후 단정 | "치료 효과가 없을 것이다", "반드시 호전될 것이다" | 예후는 다변수적 판단 필요 |
| 보호자·내담자 평가 | "보호자가 협조적이지 않다" | 관계적 판단은 임상가 영역 |

**권장 대체 표현**

| 금지 표현 | 권장 표현 |
|---|---|
| ~장애가 있다 | ~어려움이 관찰된다, ~소견이 있다, ~가능성이 있다 |
| ~로 진단된다 | 추가 평가가 권장된다 |
| ~이 확인된다 | ~것으로 보인다, ~시사된다 |
| 반드시 ~해야 한다 | ~을 고려할 수 있다 |
| ~는 정상이다 | 현재 회기에서 연령 기대 범위 내로 나타났다 |

**수치 인용 원칙**

수치는 세션 데이터를 그대로 인용하고 임의로 만들지 않습니다.

올바른 예: "이번 회기 MLU-m은 2.3으로, 만 4세 기대 범위(3.0~4.5) 하단에 해당하는 것으로 보인다."
잘못된 예: "MLU 2.3은 매우 낮은 수준으로 심각한 언어발달지연을 나타낸다."

**초안 명시 의무**

리포트 상단 또는 하단에 "본 SOAP Note는 AI가 생성한 초안으로, 담당 언어재활사의 검토·수정 후 사용해야 합니다."를 포함해야 합니다.

**언어재활사 검토 권고 항목**

진단명 포함 문장, 연령 규준 비교 해석, 중재 목표 제안, 보호자 교육 내용, 의뢰(referral) 권고.

#### 근거 문헌

- ASHA (2016). *Scope of Practice in Speech-Language Pathology.* Rockville, MD: American Speech-Language-Hearing Association. 언어재활사의 업무 범위와 진단 권한을 정의합니다.
- 대한언어재활사협회 (2020). *언어재활사 윤리강령.* 근거 기반 서비스 제공과 전문가 역할 한계 명시 의무를 규정합니다.
- WHO (2001). *International Classification of Functioning, Disability and Health (ICF).* 장애 분류와 기능적 의사소통 목표의 프레임워크. 진단보다 기능적 영향을 중심으로 기술하도록 권장합니다.

---

## 4. source_type 설계

P0 문서는 기존 `clinical_guide`, `research_paper`와 구분되는 두 가지 신규 `source_type`을 사용합니다. `source_type`은 `ChunkMetadata`에 저장되며, `chunker.py`가 이를 읽어 문서 유형에 적합한 청크 크기를 자동 선택합니다.

| source_type | chunk_size | overlap | 설계 의도 |
|---|---|---|---|
| `scoring_rule` | 150자 | 30자 | 계산 규칙은 짧고 독립적인 규칙 단위로 저장. 300자 청크에 여러 규칙이 묶이면 LLM이 규칙을 혼동. |
| `safety_rule` | 100자 | 20자 | 금지 표현 하나가 단독 청크여야 검색 시 정확히 나옴. 허용/금지 표현이 한 청크에 섞이면 안 됨. |
| `clinical_guide` | 300자 | 50자 | 기존 기본값 유지. |
| `research_paper` | 500자 | 80자 | 논문 맥락 보존. |

예를 들어 `doc_report_safety_rule`의 "~장애가 있다 → 사용 금지" 규칙이 100자 청크로 저장되면, "보고서에 어떤 표현을 쓰면 안 되나요?"라는 쿼리에 해당 청크 하나만 정확하게 검색됩니다. 150자나 300자 청크였다면 허용 표현과 금지 표현이 섞인 청크가 반환될 수 있습니다.

---

## 5. DOC_METADATA 등록 내용

`scripts/ingest_rag_docs.py`의 `DOC_METADATA`에 5개 문서가 등록됩니다. 이 매핑이 있어야 `scan_docs()` 실행 시 정확한 메타데이터로 `ChunkMetadata`가 생성됩니다.

```python
"doc_metric_exception_rule": {
    "source_type": "scoring_rule",
    "age_group": "all",
    "language_area": ["expressive_language", "vocabulary", "phonology", "narrative_discourse", "fluency"],
    "metric": ["mlu_morpheme", "ttr", "ndw", "pcc", "ciu_count"],
    "clinical_task": ["assessment"],
    "assessment_tool": ["K-ALAS"],
},
"doc_metric_mlu_korean_rule": {
    "source_type": "scoring_rule",
    "age_group": "preschool",
    "language_area": ["expressive_language", "morphosyntax"],
    "metric": ["mlu_morpheme", "llu_morpheme"],
    "clinical_task": ["assessment", "report_generation"],
    "assessment_tool": ["K-ALAS"],
},
"doc_metric_pcc_korean_rule": {
    "source_type": "scoring_rule",
    "age_group": "preschool",
    "language_area": ["phonology"],
    "metric": ["pcc"],
    "clinical_task": ["assessment", "report_generation"],
    "assessment_tool": ["U-TAP2", "APAC"],
},
"doc_metric_ciu_korean_rule": {
    "source_type": "scoring_rule",
    "age_group": "adult",
    "language_area": ["narrative_discourse", "functional_communication"],
    "metric": ["ciu_count", "ciu_ratio", "ciu_per_minute"],
    "clinical_task": ["assessment", "report_generation"],
    "assessment_tool": [],
},
"doc_report_safety_rule": {
    "source_type": "safety_rule",
    "age_group": "all",
    "language_area": ["clinical_documentation"],
    "metric": [],
    "clinical_task": ["report_generation"],
    "assessment_tool": [],
},
```

---

## 6. 기대 효과

### 계산 근거 확보

| 이전 | 이후 |
|---|---|
| "MLU 2.3입니다" → Claude가 계산 기준 없이 해석 | "MLU 2.3입니다" → 형태소 단위 기준, 제외 기준 조회 → 근거 있는 해석 |
| "PCC 65%입니다" → 오류 유형 분류 기준 없음 | "PCC 65%입니다" → 대치/생략/왜곡 분류 기준 조회 → 구체적 오류 유형 언급 가능 |
| 간투사 처리 기준 없음 → 분석자마다 다른 결과 | 공통 제외 기준 문서 → 일관된 해석 근거 제공 |

### 안전 리포트 생성

| 이전 | 이후 |
|---|---|
| "MLU 2.3으로 언어발달지연이 확인된다" (단정) | "MLU 2.3은 만 4세 기대 범위 하단에 해당하는 것으로 보인다" (소견) |
| 진단 확정 문구 포함 가능 | safety_rule 청크가 검색되어 금지 표현 자동 회피 |
| AI 초안 명시 없음 | 초안 명시 문구가 항상 포함됨 |

### RAG 검색 커버리지

P0 문서는 총 5개의 새로운 `source_type: scoring_rule / safety_rule` 청크를 pgvector에 추가합니다. 기존에는 "MLU 계산에서 반복 발화를 어떻게 처리하나요?" 같은 쿼리에 매칭되는 청크가 없었습니다. P0 문서 인제스트 후에는 `doc_metric_exception_rule` 청크가 검색됩니다.

---

## 7. 참고문헌

Brown, R. (1973). *A first language: The early stages.* Cambridge, MA: Harvard University Press.

Miller, J. F. (1981). *Assessing language production in children: Experimental procedures.* Baltimore: University Park Press.

Miller, J. F., & Iglesias, A. (2012). *Systematic Analysis of Language Transcripts (SALT), Research Version 2012* [Computer software]. Madison, WI: SALT Software.

Nicholas, L. E., & Brookshire, R. H. (1993). A system for quantifying the informativeness and efficiency of the connected speech of adults with aphasia. *Journal of Speech and Hearing Research*, 36(2), 338–350.

Kong, A. P. H. (2009). The use of main concept analysis to examine the informativeness and efficiency of the connected speech of Cantonese-speaking adults with aphasia. *Aphasiology*, 23(2), 201–217.

Shriberg, L. D., & Kwiatkowski, J. (1982). Phonological disorders I: A diagnostic classification system. *Journal of Speech and Hearing Disorders*, 47(3), 226–241.

Tager-Flusberg, H., Paul, R., & Lord, C. (2005). Language and communication in autism. In F. R. Volkmar, R. Paul, A. Klin, & D. Cohen (Eds.), *Handbook of autism and pervasive developmental disorders* (3rd ed., pp. 335–364). Hoboken, NJ: Wiley.

ASHA (2016). *Scope of practice in speech-language pathology.* Rockville, MD: American Speech-Language-Hearing Association.

MacWhinney, B. (2000). *The CHILDES project: Tools for analyzing talk* (3rd ed.). Mahwah, NJ: Lawrence Erlbaum.

배소영, 이승환, 한재순 (2000). *언어발달장애.* 서울: 시그마프레스.

이윤경 (2003). 언어발달지체 아동과 일반아동의 자발화 분석. *언어청각장애연구*, 8(1), 1–19.

이지연, 최성희, 최철희 (2023). 한국어 자동언어분석시스템(K-ALAS)의 신뢰도 연구. *언어청각장애연구*, 28(2), 228–244.

김민정, 하지완, 김수진, 김정미, 배소영 (2007). 우리말 조음음운평가(U-TAP) 타당도 및 신뢰도 연구. *언어청각장애연구*, 12(1), 1–21.

대한언어재활사협회 (2020). *언어재활사 윤리강령.* 서울: 대한언어재활사협회.

WHO (2001). *International classification of functioning, disability and health: ICF.* Geneva: World Health Organization.