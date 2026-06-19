# UtterAI RAG 가이드

> 처음 이 코드베이스를 접하는 사람을 위한 개요 문서.  
> 상세 코드 레퍼런스는 [RAG_IMPLEMENTATION.md](./RAG_IMPLEMENTATION.md)를 참고.

---

## RAG가 하는 일

UtterAI는 언어치료 세션을 분석해 SOAP Note 초안을 생성한다.  
이때 "MLU가 낮다"는 수치만 가지고는 좋은 SOAP를 쓸 수 없다.  
**근거 문헌**이 있어야 "MLU 2.3은 만 4세 기대치 하단에 해당하며, 표현언어 확장 목표를 고려할 수 있다"는 해석이 가능하다.

RAG(Retrieval-Augmented Generation)는 세션 지표를 보고 관련 임상 문서를 찾아와 LLM 프롬프트에 삽입하는 역할을 한다.

```
세션 지표 (MLU, TTR, PCC 등)
        ↓
    RAG 검색
        ↓
관련 임상 가이드 / 논문 청크
        ↓
  Bedrock Claude 프롬프트에 삽입
        ↓
      SOAP Note 초안
```

---

## 전체 구조: 두 개의 흐름

RAG는 **문서를 넣는 흐름(Ingest)**과 **문서를 꺼내는 흐름(Query)**으로 나뉜다.

### 1. Ingest 흐름 — 문서를 pgvector에 저장

```
docs/rag/*.txt          임상 가이드 (clinical_guide)
docs/papers/*.pdf       학술 논문 (research_paper)
        │
        ▼
ingest_rag_docs.py      파일 스캔 + 메타데이터 파싱
        │
   ┌────┴────┐
   │         │
local      dev/prod
   │         │
   ▼         ▼
직접 처리   S3 업로드 → SQS 발행
   │              │
   │         rag_ingest_worker (EKS batch)
   │              │
   └──────┬───────┘
          ▼
     chunker.py          문장 단위 분할 (300자, overlap 50자)
          ↓
  KURE-v1 임베딩          1024차원 벡터 생성
          ↓
    pgvector DB           rag_chunks 테이블에 저장
```

### 2. Query 흐름 — 세션 지표로 문서 검색

```
세션 지표 + 질문
        │
        ▼
  Kiwi 형태소 분석         키워드 추출 (명사/동사/형용사)
        │
        ▼
  ontology.yaml           키워드 → 관련어 확장
  (semantic_layer.py)     예: "MLU" → "평균 발화 길이", "형태소 수", "발화 복잡도"
        │
        ▼
  KURE-v1 임베딩          확장된 쿼리를 벡터로 변환
        │
        ▼
  pgvector 검색           cosine similarity 기준 top-k
        │
   근거 2개 이상?
        │
   YES  │  NO
        │   └─ 필터 제거 후 재검색 (1회)
        ▼
  RagEvidence 목록        score_threshold(0.5) 통과한 청크만
        │
        ▼
  LLM 프롬프트에 삽입
```

---

## 파일 구조와 역할

```
UtterAI_AI/
├── docs/
│   ├── rag/                    ← 임상 가이드 txt 파일 (인제스트 소스)
│   ├── papers/                 ← 학술 논문 pdf 파일 (인제스트 소스)
│   ├── RAG_GUIDE.md            ← 지금 이 파일
│   ├── RAG_IMPLEMENTATION.md   ← 코드 레퍼런스 (상세)
│   └── RAG_KNOWLEDGE_BASE_DESIGN.md  ← 지식베이스 설계 (문서 투입 계획)
│
├── scripts/
│   └── ingest_rag_docs.py      ← 문서 인제스트 실행 스크립트
│
└── app/
    ├── models/
    │   └── embedding_kure.py   ← KURE-v1 임베딩 모델 래퍼
    │
    ├── rag/
    │   ├── ontology.yaml       ← 도메인 개념 사전 (쿼리 확장 기반)
    │   ├── semantic_layer.py   ← 키워드 → ontology 확장 로직
    │   ├── chunker.py          ← 텍스트 → 청크 분할
    │   ├── ingest.py           ← 파일 읽기 + 인제스트 진입점
    │   ├── vector_store.py     ← pgvector ORM (upsert / search)
    │   ├── rag_graph.py        ← LangGraph 쿼리 파이프라인
    │   ├── retriever.py        ← rag_graph 래퍼 (외부 호출용)
    │   └── prompt_templates.py ← Bedrock Claude 프롬프트 빌더
    │
    ├── workers/
    │   └── rag_ingest_worker.py  ← SQS 폴링 + 인제스트 처리 (dev/prod)
    │
    └── api/
        └── rag.py              ← POST /ai/rag/query, POST /ai/rag/ingest
```

---

## 핵심 개념 3가지

### 1. ChunkMetadata — 모든 문서 청크에 붙는 태그

```python
ChunkMetadata(
    document_id   = "doc_language_sample_metrics",   # 문서 식별자
    title         = "언어표본분석 핵심지표 가이드",
    source_type   = "clinical_guide",   # clinical_guide | research_paper
    age_group     = "preschool",        # infant_toddler | preschool | school_age | adult | all
    language_area = "expressive_language",  # 검색 필터로 사용
    metric        = ["mlu_morpheme", "ndw"],
)
```

검색 시 `language_area`, `age_group`을 필터로 써서 관련 없는 문서를 사전에 제거한다.  
**이 태그가 없거나 잘못 달리면 검색 정밀도가 낮아진다.**

### 2. ontology.yaml — 의미 확장 사전

Kiwi가 질문에서 "MLU"라는 단어를 추출하면, ontology는 이것을 자동으로 관련어로 확장한다.

```yaml
MLU:
  ko: "평균 발화 길이"
  related_terms:
    - "평균 발화 길이"
    - "형태소 수"
    - "발화 복잡도"
    - "표현언어"
    - "MLU-w"
    - "MLU-m"
  metrics: ["mlu_morpheme"]
  language_area: ["expressive_language"]
```

이 확장 덕분에 사용자가 "MLU"라고 물어도 "평균 발화 길이"가 키워드로 쓰인 문서도 검색된다.  
**새 도메인 개념이 추가되면 ontology.yaml에도 반드시 추가해야 한다.**

### 3. LangGraph — 재검색 루프

단순 검색이 아니라 결과가 부족하면 범위를 넓혀 재시도하는 루프 구조다.

```
retrieve → 근거 부족 → fallback_retrieve (필터 제거) → finalize
retrieve → 근거 충분 → finalize
```

재시도는 1회로 제한. 결과가 없어도 무한 루프 없이 종료된다.

---

## 문서 추가 방법

### Step 1. 파일 배치

```
docs/rag/<document_id>__<제목>.txt      임상 가이드
docs/papers/<document_id>__<제목>.pdf   학술 논문
```

파일명에서 `__` 앞부분이 `document_id`, 뒷부분이 `title`로 파싱된다.

### Step 2. 필요하면 ontology.yaml 업데이트

새 문서에 새로운 임상 개념이 포함되어 있다면 `app/rag/ontology.yaml`에 추가한다.

### Step 3. 인제스트 실행

```bash
# 로컬 환경 (pgvector 직접 저장)
APP_ENV=local uv run python scripts/ingest_rag_docs.py

# dev/prod (S3 → SQS → worker)
APP_ENV=dev uv run python scripts/ingest_rag_docs.py

# 이미 S3에 있어도 SQS 재발행하고 싶을 때
uv run python scripts/ingest_rag_docs.py --force
```

이미 인제스트된 문서는 자동으로 건너뛴다.

---

## 검색 테스트 방법

서버를 띄운 상태에서 API로 검색을 테스트할 수 있다.

```bash
curl -X POST http://localhost:8000/ai/rag/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "MLU가 낮은 만 4세 아동의 표현언어 중재 전략은?",
    "filters": {"age_group": "preschool"}
  }'
```

응답에서 `evidence` 배열의 `score` 값을 보고 검색 품질을 확인한다.  
score 0.5 미만 청크는 SOAP 생성에 사용되지 않는다.

---

## 자주 하는 실수

| 상황 | 원인 | 해결 |
|---|---|---|
| `docs/rag/`에 파일 추가했는데 검색이 안 됨 | 인제스트 미실행 | `ingest_rag_docs.py` 실행 |
| 검색 결과 score가 전반적으로 낮음 | ontology에 관련 concept 없음 | `ontology.yaml`에 관련어 추가 |
| 엉뚱한 문서가 검색됨 | ChunkMetadata의 `language_area` 미설정 | 파일명 규칙 확인 또는 메타데이터 수동 지정 |
| PDF 인식이 안 됨 | pymupdf 미설치 | `uv add pymupdf` |
| 로컬에서 인제스트 오류 | pgvector 미활성화 | `DATABASE_SETUP.md` 참고 |

---

## 환경별 차이

| 항목 | local | dev / prod |
|---|---|---|
| 인제스트 경로 | `docs/` → pgvector 직접 | `docs/` → S3 → SQS → worker → pgvector |
| 벡터 DB | 로컬 PostgreSQL + pgvector | RDS PostgreSQL + pgvector |
| 임베딩 실행 위치 | 로컬 CPU | EKS batch-worker (GPU 가능) |
| worker 필요 여부 | 불필요 | 필요 (`rag_ingest_worker` 실행 중이어야 함) |

---

## 관련 문서

- [RAG_IMPLEMENTATION.md](./RAG_IMPLEMENTATION.md) — 코드 레벨 상세 설명
- [RAG_KNOWLEDGE_BASE_DESIGN.md](./RAG_KNOWLEDGE_BASE_DESIGN.md) — 지식베이스 문서 투입 계획 (어떤 문서를 넣을 것인가)
- [DATABASE_SETUP.md](./DATABASE_SETUP.md) — pgvector 환경 구성