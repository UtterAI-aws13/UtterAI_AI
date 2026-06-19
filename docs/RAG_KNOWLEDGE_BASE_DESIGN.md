# RAG 지식베이스 설계

## 현재 상태

### 보유 문서
| 파일 | source_type | languagearea |
|---|---|---|
| doc_mlu_guide | clinical_guide | expressive_language |
| doc_ttr_ndw | clinical_guide | vocabulary |
| doc_latency | clinical_guide | pragmatics |
| doc_soap_template | clinical_guide | clinical_documentation |
| doc_asd_slp_subjectivity | research_paper | pragmatics |
| doc_language_sample_analysis | research_paper | expressive_language |
| doc_utterance_analysis | research_paper | expressive_language |

### ontology 커버리지 (현재)
`expressive_language`, `vocabulary`, `pragmatics`, `clinical_documentation`, `speech_processing`

**문제**: 아동 + 표현언어 중심. 성인 대상군, 조음·음운, 형태통사, 인지-의사소통 전무.

---

## language_area 확장

| 추가 영역 | 설명 | 주요 대상 |
|---|---|---|
| `receptive_language` | 수용언어, 이해, 지시 따르기 | 아동·성인 공통 |
| `morphosyntax` | 형태통사 — 조사·어미·문법형태소 | 아동 |
| `phonology` | 음운·조음 — PCC, 음운변동, 말소리 | 아동 |
| `narrative_discourse` | 이야기·담화 — 이야기 문법, CIU, 담화 정보량 | 아동·성인 공통 |
| `cognitive_communication` | 인지-의사소통 — TBI, 치매, 우반구 손상 | 성인 |
| `fluency` | 유창성 — 말더듬, 비유창성 | 아동·성인 공통 |
| `motor_speech` | 말운동 — 마비말장애, 말실행증 | 성인 |
| `voice` | 음성장애 | 성인 |
| `aac` | 보완대체의사소통 | 아동·성인 공통 |
| `functional_communication` | 기능적 의사소통 — FCM, 일상 의사소통 | 성인 |

---

## age_group 표준화

| 값 | 범위 | 예시 대상 |
|---|---|---|
| `infant_toddler` | 0~24개월 | SELSI, MCDI-K, 초기 의사소통 |
| `preschool` | 2~6세 | PRES, MLU, TTR, ASD 조기 중재 |
| `school_age` | 6~12세 | LSSC, 이야기 중재, 읽기·쓰기 언어 |
| `adult` | 성인 | 실어증, TBI, 마비말장애, 치매 |
| `all` | 대상군 무관 | SOAP 양식, 계산식, 일반 임상 원칙 |

---

## 문서 투입 설계

### P1 — 즉시 작성·추가 (아동)

| document_id | 제목 | source_type | age_group | language_area |
|---|---|---|---|---|
| `doc_llu_guide` | LLU(최장발화길이) 해석 가이드 | clinical_guide | preschool | expressive_language |
| `doc_mlu_types` | MLU-w vs MLU-m 차이 및 한국어 적용 기준 | clinical_guide | preschool | morphosyntax |
| `doc_grammatical_morpheme` | 격조사·문법형태소 오류 유형 및 중재 접근 | clinical_guide | preschool | morphosyntax |
| `doc_pcc_guide` | PCC 계산·해석 가이드 (U-TAP2/APAC 연계) | clinical_guide | preschool | phonology |
| `doc_assessment_tools_child` | PRES/SELSI/REVT 점수 해석 및 연령 규준 | clinical_guide | preschool | expressive_language |

### P1 — 즉시 작성·추가 (성인, 신규 영역)

| document_id | 제목 | source_type | age_group | language_area |
|---|---|---|---|---|
| `doc_ciu_guide` | CIU / %CIU / CIU/min 계산·해석 가이드 | clinical_guide | adult | narrative_discourse |
| `doc_aphasia_types` | 실어증 유형별 특성 (Broca, Wernicke, 전도성, 전반성) | clinical_guide | adult | expressive_language |
| `doc_pkwab_guide` | PK-WAB 하위검사 해석 가이드 | clinical_guide | adult | expressive_language |

### P2 — Bedrock Agent 자동 수집 + 별도 작성 (아동)

| document_id | 제목 | source_type | age_group | language_area |
|---|---|---|---|---|
| `doc_asd_pragmatics` | ASD 아동 화용·사회적 의사소통 평가 체크리스트 | clinical_guide | preschool | pragmatics |
| `doc_dld_vs_delay` | 단순언어발달지연 vs DLD 감별 가이드 | clinical_guide | preschool | expressive_language |
| `doc_milieu_teaching` | 환경중심언어중재 전략 (모델링·시간지연·우발교수) | clinical_guide | preschool | expressive_language |
| `doc_narrative_intervention` | 이야기 중재 구조 가이드 (이야기 문법, 에피소드 구조) | clinical_guide | school_age | narrative_discourse |

### P2 — Bedrock Agent 자동 수집 + 별도 작성 (성인)

| document_id | 제목 | source_type | age_group | language_area |
|---|---|---|---|---|
| `doc_adult_discourse` | 성인 담화 분석 지표 (WPM, Main Concept Analysis) | clinical_guide | adult | narrative_discourse |
| `doc_tbi_cognitive_comm` | TBI 인지-의사소통 평가 체크리스트 | clinical_guide | adult | cognitive_communication |
| `doc_dementia_language` | 치매 단계별 언어 변화 특성 | clinical_guide | adult | cognitive_communication |
| `doc_dysarthria_types` | 마비말장애 유형별 특성 및 말 명료도 평가 | clinical_guide | adult | motor_speech |

### P3 — 나중에

| document_id | 제목 | source_type | age_group | language_area |
|---|---|---|---|---|
| `doc_fcm_guide` | 기능적 의사소통 척도(FCM) 해석 가이드 | clinical_guide | adult | functional_communication |
| `doc_aac_child` | 아동 AAC 대상 선별 기준 및 초기 어휘 선정 원칙 | clinical_guide | preschool | aac |
| `doc_aac_adult` | 성인 AAC 도입 판단 기준 | clinical_guide | adult | aac |
| `doc_fluency_guide` | 말더듬 유형 및 유창성 평가 가이드 | clinical_guide | all | fluency |

---

## Bedrock Agent 논문 검색 키워드

### 아동
```
language sample analysis Korean children
MLU morpheme Korean preschool
specific language impairment Korean
phonological disorder Korean children PCC
ASD Korean social communication intervention
K-ALAS Korean automatic language analysis
grammatical morpheme acquisition Korean
```

### 성인
```
aphasia discourse analysis CIU
correct information unit aphasia Korean
traumatic brain injury cognitive communication assessment
dysarthria intelligibility assessment Korean
dementia language characteristics
apraxia of speech treatment evidence
functional communication measure aphasia
```

---

## ontology.yaml 추가 concept

### 신규 추가

```yaml
PCC:
  ko: "자음정확도"
  related_terms:
    - "자음 정확도"
    - "조음 정확도"
    - "말소리 오류"
    - "음소 오류"
    - "U-TAP2"
    - "APAC"
  metrics: ["pcc"]
  language_area: ["phonology"]

LLU:
  ko: "최장 발화 길이"
  related_terms:
    - "최장발화길이"
    - "발화 복잡도"
    - "문장 복잡성"
    - "Longest Length of Utterance"
  metrics: ["llu_morpheme", "llu_word"]
  language_area: ["expressive_language"]

CIU:
  ko: "맥락적 정보 단위"
  related_terms:
    - "Correct Information Unit"
    - "담화 정보량"
    - "정보 전달 효율성"
    - "%CIU"
    - "CIU/min"
    - "분당 CIU"
    - "Main Concept Analysis"
  metrics: ["ciu_count", "ciu_ratio", "ciu_per_minute"]
  language_area: ["narrative_discourse", "functional_communication"]

grammatical_morpheme:
  ko: "문법형태소"
  related_terms:
    - "조사 오류"
    - "어미 오류"
    - "격조사"
    - "주격조사"
    - "목적격조사"
    - "연결어미"
    - "종결어미"
    - "문법형태소 누락"
    - "형태통사"
  language_area: ["morphosyntax"]

aphasia:
  ko: "실어증"
  related_terms:
    - "Broca 실어증"
    - "Wernicke 실어증"
    - "전도성 실어증"
    - "전반성 실어증"
    - "이름대기 장애"
    - "PK-WAB"
    - "K-BNT"
    - "단어 찾기 어려움"
    - "착어"
    - "의미착어"
    - "음운착어"
  language_area: ["expressive_language", "receptive_language"]

cognitive_communication:
  ko: "인지-의사소통"
  related_terms:
    - "TBI"
    - "외상성 뇌손상"
    - "치매"
    - "우반구 손상"
    - "주의 장애"
    - "기억 장애"
    - "집행기능"
    - "담화 조직화"
    - "추론"
  language_area: ["cognitive_communication"]

turn_taking:
  ko: "대화 차례"
  related_terms:
    - "차례 주고받기"
    - "발화 교대"
    - "반응 시작"
    - "대화 개시"
    - "화용 상호작용"
    - "자발 발화"
  language_area: ["pragmatics"]

motor_speech:
  ko: "말운동장애"
  related_terms:
    - "마비말장애"
    - "말실행증"
    - "말 명료도"
    - "조음 오류"
    - "말속도"
    - "운율"
    - "dysarthria"
    - "apraxia of speech"
  language_area: ["motor_speech"]
```

### 기존 concept 보강

```yaml
# MLU에 MLU-w, LLU, K-ALAS 관련어 추가
MLU:
  related_terms에 추가:
    - "MLU-w"
    - "MLU-m"
    - "MLU-e"
    - "LLU"
    - "K-ALAS"
    - "어절"
    - "발화 수"

# TTR에 K-ALAS 지표 추가
TTR:
  related_terms에 추가:
    - "어휘 다양성 지수"
    - "K-ALAS"
```

---

## 구현 순서

```
1. ontology.yaml 신규 concept 추가        ← 검색 품질 즉시 향상
2. P1 clinical_guide 문서 작성 (8개)      ← 성인 대상군 커버
3. Bedrock Agent 구현                     ← 논문 자동 수집
4. P2 문서 자동 수집 + 별도 작성
5. P3 문서 추가
```