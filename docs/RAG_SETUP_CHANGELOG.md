# RAG 데이터 세팅 작업 기록

> 작성일: 2026-06-19  
> 대상 브랜치: dev  
> 작업 범위: RAG 지식베이스 품질 개선 — 1단계 코드 변경

---

## 목차

1. [작업 배경](#1-작업-배경)
2. [작업 전 문제 진단](#2-작업-전-문제-진단)
3. [변경 파일 목록](#3-변경-파일-목록)
4. [변경 내용 상세](#4-변경-내용-상세)
   - 4-1. ingest_rag_docs.py — DOC_METADATA 추가
   - 4-2. ontology.yaml — 개념 7개 추가
   - 4-3. schemas/rag.py — ChunkMetadata 스키마 확장
   - 4-4. rag/chunker.py — source_type별 청크 크기 자동 선택
   - 4-5. rag/vector_store.py — 필터 로직 수정
5. [전체 RAG 설계](#5-전체-rag-설계)
6. [다음 단계 계획](#6-다음-단계-계획)

---

## 1. 작업 배경

UtterAI는 언어치료 세션을 분석해 SOAP Note 초안을 생성하는 AI 서비스입니다. 세션에서 측정된 MLU, TTR, PCC, CIU 등의 수치를 근거 문헌과 연결해 임상적으로 유의미한 해석을 제공하는 것이 핵심이며, 이 과정이 **RAG(Retrieval-Augmented Generation)** 파이프라인입니다.

```
세션 지표 (MLU, TTR, PCC 등)
        ↓
    RAG 검색 — 관련 임상 문서 조회
        ↓
Bedrock Claude — 문서를 근거로 SOAP Note 초안 생성
```

RAG가 올바른 문서를 찾지 못하면 Claude는 "MLU 2.3"이라는 숫자를 받아도 어떤 연령에서 어떤 의미인지, 어떤 중재 방향을 제안해야 하는지 알 수 없습니다. 따라서 RAG 지식베이스의 품질이 전체 서비스 품질을 결정합니다.

이번 작업은 코드베이스에 이미 구현된 RAG 파이프라인이 **실제로 올바르게 작동하도록** 메타데이터와 검색 로직을 정비한 1단계 작업입니다.

---

## 2. 작업 전 문제 진단

### 2-1. 메타데이터 공백 (가장 심각)

RAG 검색 파이프라인은 `language_area`를 필터로 사용해 관련 없는 문서를 사전에 제거합니다. 예를 들어 "MLU가 낮은 아동" 관련 질문이 들어오면 `language_area=expressive_language` 필터를 걸어 성인 담화 문서나 음성장애 문서가 검색되지 않도록 합니다.

그런데 작업 전 `scripts/ingest_rag_docs.py`의 `scan_docs()` 함수는 **모든 문서에 동일한 메타데이터를 적용**하고 있었습니다.

```python
# 작업 전 — 모든 문서에 동일
ChunkMetadata(
    document_id=doc_id,
    chunk_id="",
    title=title,
    source_type=source_type,
    age_group="all",       # 항상 "all"
    metric=[],             # 항상 빈 리스트
    # language_area 없음 → None으로 저장
)
```

이 상태에서 인제스트된 문서는 필터링이 전혀 작동하지 않습니다. 아동 MLU 질문에 성인 실어증 문서가, 성인 CIU 질문에 아동 발음 검사 문서가 검색 결과로 올라올 수 있습니다.

### 2-2. language_area 단일 값 한계

기존 `ChunkMetadata`의 `language_area`는 `str | None`, 즉 단일 문자열이었습니다. 그런데 실제 임상 가이드 문서는 여러 영역을 동시에 다룹니다.

예를 들어 `doc_adult_slp_guide`(성인 언어재활 평가 및 지표 가이드)는 실어증(`expressive_language`), 담화 분석(`narrative_discourse`), 마비말장애(`motor_speech`), 인지-의사소통(`cognitive_communication`), SOAP 작성(`clinical_documentation`)을 모두 포함합니다. 단일 `language_area`로는 이 문서가 `narrative_discourse` 질문에서 걸러져 검색되지 않는 문제가 생깁니다.

### 2-3. 문서 유형 구분 부재

기존 `source_type`은 `clinical_guide`와 `research_paper` 두 가지뿐이었습니다. 그런데 앞으로 추가할 문서들은 성격이 전혀 다릅니다.

- 계산 규칙 문서: "MLU 계산 시 반복 발화는 제외한다"
- 한국어 언어 규칙 문서: "어절, 낱말, 형태소의 차이와 선택 기준"
- safety 규칙 문서: "리포트에서 '장애가 있다'는 단정적 표현을 쓰지 않는다"

이 문서들은 임상 해석 가이드와 다르게 **짧고 정밀한 규칙 단위**로 저장해야 합니다. 같은 300자 청크로 저장하면 규칙이 중간에 잘려나가거나 여러 규칙이 섞입니다.

### 2-4. ontology 누락 개념

Kiwi + ontology 기반 쿼리 확장이 핵심 검색 품질 요소인데, 한국어 언어치료에서 자주 쓰이는 개념 여러 개가 빠져 있었습니다.

- "어절"이라는 단어를 검색해도 관련 개념이 확장되지 않음
- "격조사 누락"이 "조사 오류"와 연결되지 않음
- "음운변동"이 대치/생략/동화와 연결되지 않음
- "비유창성"이 반복/연장/막힘과 연결되지 않음

---

## 3. 변경 파일 목록

| 파일 | 변경 유형 | 핵심 내용 |
|---|---|---|
| `scripts/ingest_rag_docs.py` | 기능 추가 | DOC_METADATA 매핑 테이블 추가, 새 필드 전달 |
| `app/rag/ontology.yaml` | 내용 추가 | 신규 개념 7개 추가 |
| `app/schemas/rag.py` | 스키마 변경 | ChunkMetadata 필드 확장 |
| `app/rag/chunker.py` | 로직 추가 | source_type별 청크 파라미터 자동 선택 |
| `app/rag/vector_store.py` | 버그 수정 | list[str] language_area 필터 로직 수정 |

---

## 4. 변경 내용 상세

### 4-1. `scripts/ingest_rag_docs.py` — DOC_METADATA 추가

#### 무엇을 했나

`scan_docs()` 함수 위에 `DOC_METADATA` 딕셔너리를 추가했습니다. 키는 `document_id`이며, 값은 해당 문서에 적용할 메타데이터 오버라이드입니다.

```python
DOC_METADATA: dict[str, dict] = {
    "doc_language_sample_metrics": {
        "age_group": "preschool",
        "language_area": ["expressive_language", "vocabulary", "pragmatics", "phonology"],
        "metric": ["mlu_morpheme", "llu_morpheme", "ndw", "ntw", "ttr", "pcc"],
        "clinical_task": ["assessment", "report_generation"],
        "assessment_tool": ["K-ALAS"],
    },
    "doc_korean_morphosyntax": {
        "age_group": "preschool",
        "language_area": ["morphosyntax"],
        "metric": [],
        "clinical_task": ["assessment", "goal_writing"],
        "assessment_tool": [],
    },
    "doc_adult_slp_guide": {
        "age_group": "adult",
        "language_area": ["expressive_language", "narrative_discourse", "motor_speech",
                          "cognitive_communication", "clinical_documentation"],
        "metric": ["ciu_count", "ciu_ratio", "ciu_per_minute"],
        "clinical_task": ["assessment", "report_generation", "goal_writing"],
        "assessment_tool": ["PK-WAB", "K-BNT"],
    },
    # ... (8개 문서 전체 매핑)
}
```

`scan_docs()`는 파일 스캔 시 `DOC_METADATA.get(doc_id, {})`로 오버라이드를 조회하고 `ChunkMetadata`에 적용합니다.

#### 왜 했나

새 문서를 추가할 때마다 수동으로 `DOC_METADATA`에 항목을 추가하도록 강제하기 위해서입니다. 메타데이터 없이 인제스트되는 문서가 생기는 것을 구조적으로 방지합니다. 매핑이 없으면 `age_group="all"`, `language_area=[]`로 폴백하여 필터링 대상에서 제외됩니다.

#### 기대 효과

- 8개 기존 문서 모두 `language_area`, `age_group`, `metric`, `clinical_task`, `assessment_tool`이 정확하게 저장됨
- LangGraph 파이프라인의 `expand_query` → `get_metadata_filters` → `retrieve` 필터링이 실제로 작동함
- "5세 아동 MLU" 질문 → `expressive_language` 필터 → 성인 담화 문서 제외 → 관련 아동 임상 가이드만 검색

#### 현재 매핑된 문서

| document_id | age_group | language_area | metric | clinical_task |
|---|---|---|---|---|
| doc_language_sample_metrics | preschool | expressive_language, vocabulary, pragmatics, phonology | mlu, llu, ndw, ntw, ttr, pcc | assessment, report_generation |
| doc_korean_morphosyntax | preschool | morphosyntax | — | assessment, goal_writing |
| doc_adult_slp_guide | adult | expressive_language, narrative_discourse, motor_speech, cognitive_communication, clinical_documentation | ciu_count, ciu_ratio, ciu_per_minute | assessment, report_generation, goal_writing |
| doc_child_slp_population | preschool | pragmatics, expressive_language, phonology, narrative_discourse | mlu, ndw, ttr, pcc | assessment, intervention |
| doc_child_assessment_tools | preschool | expressive_language, receptive_language, phonology | mlu, ndw, pcc | assessment |
| doc_asd_slp_subjectivity (논문) | preschool | pragmatics | — | assessment |
| doc_utterance_analysis (논문) | preschool | expressive_language | mlu | assessment |
| doc_language_sample_analysis (논문) | preschool | expressive_language | mlu, ndw, ttr | assessment |

---

### 4-2. `app/rag/ontology.yaml` — 개념 7개 추가

#### 무엇을 했나

기존 ontology에 없던 한국어 언어치료 핵심 개념 7개를 추가했습니다.

| concept 키 | 한국어 표기 | 연결된 language_area |
|---|---|---|
| `eojeol` | 어절 | morphosyntax, expressive_language |
| `case_particle` | 격조사 | morphosyntax |
| `connective_ending` | 연결어미 | morphosyntax |
| `phonological_process` | 음운변동 | phonology |
| `disfluency` | 비유창성 | fluency, pragmatics |
| `main_concept` | 핵심개념분석 | narrative_discourse |
| `functional_goal` | 기능적 목표 | functional_communication, clinical_documentation |

각 concept는 `ko`(한국어 표기), `related_terms`(동의어·관련어 목록), `language_area`(연결 영역), 해당하는 경우 `metrics`(관련 측정 지표)로 구성됩니다.

#### eojeol (어절) 추가 예시

```yaml
eojeol:
  ko: "어절"
  related_terms:
    - "띄어쓰기 단위"
    - "낱말 단위"
    - "word unit"
    - "Korean word"
    - "어절 수"
    - "NTJ"
    - "NDJ"
  language_area:
    - "morphosyntax"
    - "expressive_language"
```

#### 왜 했나

ontology는 쿼리 확장의 근간입니다. Kiwi가 사용자 질문에서 "어절"을 추출하면 ontology가 "NTJ", "NDJ", "띄어쓰기 단위"까지 확장해 더 많은 관련 청크를 검색합니다.

추가된 개념들이 없으면 다음 상황에서 검색이 실패합니다:

- "격조사 오류가 많은 아동" → `case_particle` 개념 없이는 "주격조사", "목적격조사"와 연결되지 않음
- "음운변동 분석" → `phonological_process` 없이는 "대치", "생략", "동화"와 연결되지 않음
- "비유창성 평가" → `disfluency` 없이는 "반복", "연장", "막힘", "P-FA"와 연결되지 않음
- "기능적 목표" → `functional_goal` 없이는 "ICF", "FCM", "일상 의사소통"과 연결되지 않음

#### 기대 효과

- 쿼리 확장 커버리지 향상: 사용자가 어떤 동의어·관련어로 질문해도 같은 문서가 검색됨
- 형태통사(`morphosyntax`) 영역 검색 품질 개선: 이전에는 ontology에 morphosyntax 관련 concept가 `grammatical_morpheme` 하나뿐이었으나 `case_particle`, `connective_ending`, `eojeol` 추가로 훨씬 세밀하게 커버됨
- 음운 영역 검색 품질 개선: `phonological_process`가 U-TAP2, APAC, 오류 패턴과 연결됨
- 담화/기능 영역 진입: `main_concept`, `functional_goal`이 성인 재활 관련 쿼리 확장에 기여

---

### 4-3. `app/schemas/rag.py` — ChunkMetadata 스키마 확장

#### 무엇을 했나

`ChunkMetadata` Pydantic 모델에 필드 3개를 추가하고, `language_area` 타입을 변경했습니다.

**변경 전:**
```python
class ChunkMetadata(BaseModel):
    document_id: str
    chunk_id: str
    title: str
    source_type: str        # clinical_guide, research_paper만 존재
    age_group: str | None = None
    language_area: str | None = None   # 단일 문자열
    metric: list[str] = []
    page: int | None = None
    section: str | None = None
    created_at: datetime | None = None
```

**변경 후:**
```python
class ChunkMetadata(BaseModel):
    document_id: str
    chunk_id: str
    title: str
    source_type: str
    # source_type 허용값:
    #   clinical_guide       임상 해석 가이드
    #   research_paper       논문 전문
    #   research_abstract    논문 초록 (전문 미확보)
    #   scoring_rule         지표 계산 규칙·제외 기준
    #   linguistic_rule      한국어 언어현상 규칙
    #   safety_rule          단정·진단 표현 제한
    age_group: str | None = None
    language_area: list[str] = []          # 복수 영역 지원
    metric: list[str] = []
    clinical_task: list[str] = []          # 신규
    # clinical_task 허용값: assessment, report_generation, goal_writing, intervention
    assessment_tool: list[str] = []        # 신규
    # 예: U-TAP2, PRES, PK-WAB, K-ALAS
    page: int | None = None
    section: str | None = None
    created_at: datetime | None = None
```

#### 왜 했나

**`language_area: list[str]`**  
한 문서가 여러 임상 영역을 다루는 경우(예: 성인 가이드가 실어증, 담화, 말운동, 인지-의사소통을 모두 포함) 단일 문자열로는 한 영역만 지정할 수 있어 나머지 영역 검색에서 해당 문서가 누락됩니다. `list[str]`로 바꾸면 문서가 여러 영역 필터에 동시에 걸립니다.

하위 호환성: `metadata_json`이 PostgreSQL JSONB로 저장되므로 DB 마이그레이션이 필요 없습니다. 기존에 문자열로 저장된 `language_area`는 `vector_store.py`에서 `isinstance(chunk_areas, str)` 체크로 자동 처리합니다.

**`clinical_task`**  
실제 질문은 "이 지표가 무엇인가"가 아니라 "SOAP A 섹션에 어떻게 쓰나", "중재 목표를 어떻게 설정하나" 같은 **임상 작업 맥락**을 가집니다. 이 필드를 추가하면 나중에 `clinical_task=report_generation` 필터로 SOAP/리포트 생성에 특화된 문서만 검색할 수 있습니다.

**`assessment_tool`**  
"PRES 결과를 어떻게 해석하나" 같은 질문에 PRES가 언급된 문서만 우선 검색할 수 있습니다. 평가도구 이름 기반 필터링이 가능해집니다.

#### 기대 효과

- 다영역 문서의 검색 누락 방지
- `clinical_task` 기반 필터로 목적별 문서 분리 가능 (나중에 활용)
- `assessment_tool` 기반 필터로 평가도구 연계 검색 가능 (나중에 활용)
- 앞으로 추가할 `scoring_rule`, `linguistic_rule`, `safety_rule` 문서 수용 구조 확보

---

### 4-4. `app/rag/chunker.py` — source_type별 청크 크기 자동 선택

#### 무엇을 했나

`_CHUNK_PARAMS` 딕셔너리와 `_chunk_params()` 함수를 추가하고, `make_chunks()`가 `chunk_size`/`overlap`을 명시하지 않으면 `metadata.source_type`을 보고 자동으로 선택하도록 변경했습니다.

```python
_CHUNK_PARAMS: dict[str, tuple[int, int]] = {
    "scoring_rule":       (150, 30),
    "linguistic_rule":    (200, 40),
    "safety_rule":        (100, 20),
    "research_paper":     (500, 80),
    "research_abstract":  (300, 50),
    "clinical_guide":     (300, 50),
}
```

`make_chunks()` 시그니처 변경:
```python
# 변경 전
def make_chunks(..., chunk_size: int = 300, overlap: int = 50)

# 변경 후
def make_chunks(..., chunk_size: int | None = None, overlap: int | None = None)
# None이면 source_type 보고 자동 결정
```

#### 왜 소스 타입별로 크기가 다른가

| source_type | chunk_size | 이유 |
|---|---|---|
| `scoring_rule` | 150자 | 계산 규칙은 "MLU 계산 시 반복 발화를 제외한다"처럼 짧고 독립적인 규칙 단위로 저장해야 정밀하게 검색됨. 300자 청크로 여러 규칙이 묶이면 LLM이 규칙을 혼동할 수 있음 |
| `linguistic_rule` | 200자 | 한국어 언어 규칙은 규칙 + 예시가 세트이므로 scoring_rule보다 약간 크게 허용 |
| `safety_rule` | 100자 | 금지 표현 하나가 독립된 청크여야 검색 시 정확하게 나옴. "~다"로 단정짓지 않는다" 같은 짧은 규칙이 다른 내용과 섞이면 안 됨 |
| `research_paper` | 500자 | 논문은 맥락이 끊기면 근거로서 신뢰도가 낮아짐. 방법, 결과, 결론이 이어져야 LLM이 올바른 임상적 함의를 추출할 수 있음 |
| `clinical_guide` | 300자 | 기존 검증된 기본값 유지 |

#### 기대 효과

- 앞으로 추가할 P0 문서(scoring_rule, safety_rule)가 문서 특성에 맞는 크기로 자동 청킹됨
- 계산 규칙 문서에서 "MLU는 총 형태소 수를 발화 수로 나눈 값이다"와 "반복 발화는 제외한다"가 별도 청크로 분리되어 각각 독립적으로 검색 가능
- 논문 청크가 커져서 임상적 맥락(대상군 → 방법 → 결과 → 함의)이 하나의 청크 안에 유지됨
- 외부에서 명시적으로 `chunk_size`를 넘기면 그 값이 우선 적용되므로 기존 호출 방식과 완전히 호환됨

---

### 4-5. `app/rag/vector_store.py` — 필터 로직 수정

#### 무엇을 했나

`search()` 메서드에서 `language_area` 필터를 적용하는 코드를 수정했습니다.

**변경 전:**
```python
if allowed_areas and meta.get("language_area") not in allowed_areas:
    continue
```

이 코드는 `meta.get("language_area")`가 단일 문자열이라고 가정합니다. `language_area`가 `["expressive_language", "morphosyntax"]`인 리스트라면 `["expressive_language", "morphosyntax"] not in ["expressive_language"]`는 항상 `True`가 되어 해당 청크가 필터링에서 제외됩니다.

**변경 후:**
```python
if allowed_areas:
    chunk_areas = meta.get("language_area") or []
    if isinstance(chunk_areas, str):
        chunk_areas = [chunk_areas]  # 기존 문자열 데이터 하위 호환
    if not any(area in allowed_areas for area in chunk_areas):
        continue
```

#### 왜 했나

`ChunkMetadata.language_area`가 `list[str]`으로 바뀌면서 JSONB에 저장되는 값도 리스트가 됩니다. 검색 시 필터 로직이 이전 구조 그대로였다면 **`language_area`가 있는 모든 청크가 필터에서 걸러져 검색 결과가 항상 0**이 될 수 있었습니다.

하위 호환 처리(`isinstance(chunk_areas, str)` 체크)는 기존에 문자열로 인제스트된 청크가 남아있을 때를 대비한 방어 코드입니다.

#### 기대 효과

- `language_area: ["expressive_language", "narrative_discourse"]`로 저장된 청크가 `expressive_language` 필터나 `narrative_discourse` 필터 모두에서 정상 검색됨
- 기존에 단일 문자열로 저장된 레거시 청크도 정상 처리됨

---

## 5. 전체 RAG 설계

### 5-1. 스택 구성

```
문서 저장    PostgreSQL + pgvector (rag_chunks 테이블)
임베딩       nlpai-lab/KURE-v1 (1024차원, 한국어 특화)
쿼리 확장    Kiwi 형태소 분석 + ontology.yaml 동의어 확장
검색 파이프  LangGraph StateGraph (retrieve → fallback → finalize)
생성         AWS Bedrock Claude
논문 수집    월 1회 배치 (PubMed / Semantic Scholar / RISS / DBpia / CrossRef)
배포         EKS (CPU Worker: RAG 검색, Batch Worker: 문서 인제스트)
```

### 5-2. 지식베이스 문서 유형

```
clinical_guide      임상 해석 가이드 — MLU 해석, 대상군별 특성, SOAP 작성 원칙
research_paper      학술 논문 전문 — 한국어 언어치료 관련 국내외 연구
research_abstract   논문 초록 — 전문 미확보 논문 (API 수집 시 사용)
scoring_rule        계산 규칙 — MLU/TTR/PCC/CIU 계산 단위, 포함/제외 기준    ← P0 신규
linguistic_rule     언어 규칙 — 한국어 어절/형태소/조사/어미 분석 기준          ← P0 신규
safety_rule         안전 규칙 — 리포트 단정·진단 표현 금지 목록               ← P0 신규
```

### 5-3. 쿼리 파이프라인 흐름

```
사용자 질문 (세션 지표 + 임상 맥락)
        ↓
Kiwi 형태소 분석
        → 명사(NNG/NNP), 동사(VV), 형용사(VA) 추출
        ↓
ontology.yaml 쿼리 확장
        → 키워드 → related_terms 전체 추가
        → language_area, metric 필터 생성
        ↓
KURE-v1 임베딩 (확장된 쿼리 → 1024차원 벡터)
        ↓
pgvector cosine similarity 검색 (top-k=5)
        + language_area, metric 메타데이터 필터
        ↓
score_threshold (0.5) 미만 청크 제거
        ↓
근거 2개 미만?
  YES → 필터 제거 + top-k×2로 fallback 재검색 (1회)
  NO  → finalize
        ↓
RagResult (evidence 목록) → Bedrock Claude 프롬프트 삽입
        ↓
SOAP Note 초안 생성
```

### 5-4. 메타데이터 필드 전체 목록

| 필드 | 타입 | 설명 | 검색 필터 사용 |
|---|---|---|---|
| `document_id` | str | 문서 식별자 | 특정 문서 조회 시 |
| `chunk_id` | str | 청크 식별자 | 출처 추적 |
| `title` | str | 문서 제목 | 리포트 출처 표시 |
| `source_type` | str | 문서 유형 | chunker 크기 결정 |
| `age_group` | str | 대상 연령군 | 검색 필터 |
| `language_area` | list[str] | 임상 언어 영역 | 검색 핵심 필터 |
| `metric` | list[str] | 관련 측정 지표 | 검색 필터 |
| `clinical_task` | list[str] | 임상 작업 유형 | 향후 필터 확장 |
| `assessment_tool` | list[str] | 관련 평가도구 | 향후 필터 확장 |
| `page` | int | 논문 페이지 | 출처 추적 |
| `section` | str | 문서 섹션 | 출처 추적 |

---

## 6. 다음 단계 계획

### 2단계 — P0 문서 5개 작성 (신규 source_type)

임상 수치를 어떻게 계산하고 어떤 발화를 제외하는지에 대한 규칙이 지식베이스에 없으면 Claude가 수치를 받아도 계산 근거 없이 답합니다. 이를 보완하는 문서 5개를 작성합니다.

| document_id | source_type | 핵심 내용 |
|---|---|---|
| `doc_metric_exception_rule` | scoring_rule | 반복·간투사·자기수정·불명료 발화 제외 기준 |
| `doc_metric_mlu_korean_rule` | scoring_rule | 한국어 어절/형태소/낱말 단위 선택 기준, 예시, 예외 |
| `doc_metric_pcc_korean_rule` | scoring_rule | 목표 자음 포함/제외 기준, 오류 유형 분류 |
| `doc_metric_ciu_korean_rule` | scoring_rule | CIU/%CIU/CIU-per-min 한국어 적용 기준 |
| `doc_report_safety_rule` | safety_rule | 단정·진단 표현 금지어 목록, 권장 표현 |

### 3단계 — P1 clinical_guide 보완

기존 5개 통합 문서로 커버되지 않는 영역 확인 후 추가.

### 4단계 — 논문 수집 파이프라인 구현

```
scripts/collect_papers.py
  ├─ PubMed (E-utilities API) — 의학·재활 논문
  ├─ Semantic Scholar API — 광범위, 일부 한국어
  ├─ RISS Open API — 국내 학술지 (CSD, JSLHD 등)
  ├─ DBpia API — 국내 학술지
  └─ CrossRef API — DOI 메타데이터 보강
```

- DOI 기준 중복 제거
- Bedrock Claude로 abstract → `age_group`, `language_area`, `metric` 자동 추출 및 `DOC_METADATA` 자동 생성
- 월 1회 배치 실행 → `docs/papers/` 저장 → 기존 `ingest_rag_docs.py` 파이프라인 연결

### 5단계 — P2/P3 문서 추가

학령기·성인·AAC·음성장애 등 추가 임상 가이드

### 6단계 — RAG 평가 (나중에)

- Golden QA set 20문항 이상 (질문 → 기대 검색 문서 + 답변 구조)
- RAGAS로 context precision, recall, faithfulness 측정
- 기준점(baseline) 확보 후 문서 추가 시마다 품질 회귀 확인