# RAG 구현 문서

UtterAI AI 모듈의 RAG(Retrieval-Augmented Generation) 구현 설계와 코드 구조를 설명합니다.

---

## 1. 개요

RAG는 언어치료 세션 분석 결과를 바탕으로 관련 임상 문서를 검색하고, 그 근거 위에서 SOAP Note 초안을 생성하는 역할을 합니다.

검색 엔진에 직접 질문을 던지는 대신 다음 두 단계로 분리합니다.

- **Indexing**: 치료 문서를 청크로 분할하고 벡터로 변환해 pgvector에 저장
- **Query**: 세션 지표와 발화를 바탕으로 관련 근거를 검색하고 LLM 프롬프트에 삽입

---

## 2. 파일 구조

```
app/
├── models/
│   └── embedding_kure.py       # KURE-v1 임베딩 모델 래퍼
├── rag/
│   ├── ontology.yaml           # 도메인 개념 사전 (MLU, TTR, SOAP 등)
│   ├── semantic_layer.py       # 키워드 → ontology 기반 쿼리 확장
│   ├── chunker.py              # 문서 텍스트 → 청크 분할
│   ├── ingest.py               # 문서 수집 파이프라인 진입점
│   ├── vector_store.py         # pgvector ORM + upsert / search
│   ├── rag_graph.py            # LangGraph 기반 쿼리 파이프라인
│   ├── retriever.py            # rag_graph 래퍼 (외부 호출용)
│   └── prompt_templates.py     # Bedrock Claude 입력 프롬프트 빌더
```

---

## 3. Indexing 흐름

문서를 pgvector에 저장하는 흐름입니다.

```
문서 파일 (.txt / .pdf)
  └─ ingest.py: _extract_text()          파일 읽기 (PDF: pymupdf 우선 → pdfplumber 폴백)
  └─ chunker.py: make_chunks()           문장 단위 분할 + sliding window overlap
  └─ embedding_kure.py: predict()        KURE-v1으로 청크별 1024차원 벡터 생성
  └─ vector_store.py: upsert()           rag_chunks 테이블에 청크 + 벡터 저장
```

### 3.0 지원 파일 형식

| 확장자 | 추출 방식 |
|---|---|
| `.txt` | `Path.read_text(encoding="utf-8")` |
| `.pdf` | pymupdf(`fitz`) 우선 → pdfplumber 폴백 |

PDF는 학술 논문에 포함된 수식·기호 보존이 중요하므로 pymupdf를 기본으로 사용합니다.
pymupdf가 설치되지 않으면 pdfplumber로 자동 폴백하며, 둘 다 없으면 ImportError를 발생시킵니다.

```bash
uv add pymupdf   # 권장
```

### 3.4 인제스트 스크립트

`scripts/ingest_rag_docs.py`는 `APP_ENV` 값에 따라 두 가지 모드로 동작합니다.

| `APP_ENV` | 동작 |
|---|---|
| `local` | docs/ 파일을 직접 pgvector에 ingest |
| `dev` / `prod` | docs/ 파일을 S3에 업로드 후 SQS 메시지 발행 → `rag_ingest_worker`(batch-worker)가 처리 |

`--force` 옵션을 사용하면 S3에 이미 존재하는 파일도 SQS에 재발행합니다.

**스캔 대상 디렉토리**

```
docs/
├── rag/      - *.txt  (source_type=clinical_guide)
└── papers/   - *.pdf  (source_type=research_paper)
```

**파일명 규칙**: `<document_id>__<title>.<ext>`

```
doc_mlu_guide__MLU_해석_가이드.txt        → document_id=doc_mlu_guide, title="MLU 해석 가이드"
doc_utterance__발화분석과제.pdf           → document_id=doc_utterance, title="발화분석과제"
```

`__`가 없으면 파일명 전체를 document_id로 사용합니다.

```bash
uv run python scripts/ingest_rag_docs.py
```

### 3.1 청크 분할 전략

| 파라미터 | 기본값 | 설명 |
|---|---|---|
| `chunk_size` | 300자 | 청크 최대 글자 수 |
| `overlap` | 50자 | 앞 청크에서 다음 청크로 이어지는 글자 수 |

문장 끝 문자(`.`, `!`, `?`, `。`, `？`, `！`)와 개행을 기준으로 분리합니다.
overlap은 청크 경계에서 문맥이 끊기는 것을 방지합니다.

### 3.2 rag_chunks 테이블 구조

```sql
CREATE TABLE rag_chunks (
    chunk_id       TEXT PRIMARY KEY,
    document_id    TEXT NOT NULL,
    content        TEXT NOT NULL,
    embedding      VECTOR(1024) NOT NULL,   -- KURE-v1 출력 차원
    metadata_json  JSONB                    -- ChunkMetadata 직렬화
);
```

`metadata_json`에는 `title`, `source_type`, `age_group`, `language_area`, `metric` 등이 저장되며 검색 시 필터로 활용합니다.

### 3.3 ingest 호출 예시

```python
from app.rag.ingest import ingest_document
from app.schemas import ChunkMetadata

metadata = ChunkMetadata(
    document_id="doc_001",
    chunk_id="",          # ingest 내부에서 자동 생성
    title="언어발달 평가 가이드",
    source_type="clinical_guide",
    age_group="preschool",
    language_area="expressive_language",
    metric=["mlu_morpheme", "ndw"],
)

n = await ingest_document(
    file_path="./docs/lang_dev_guide.pdf",
    metadata=metadata,
    embedding_model=embedding_model,
    vector_store=vector_store,
)
print(f"{n}개 청크 저장 완료")
```

---

## 4. Query 흐름 (LangGraph)

쿼리 파이프라인은 `rag_graph.py`에 LangGraph `StateGraph`로 구현돼 있습니다.

### 4.1 그래프 구조

```
START
  │
  ▼
extract_keywords        Kiwi 형태소 분석으로 명사/동사/형용사 키워드 추출
  │
  ▼
expand_query            ontology.yaml 기반 키워드 확장 + 메타데이터 필터 생성
  │
  ▼
retrieve                KURE-v1으로 쿼리 임베딩 → pgvector cosine similarity 검색
  │
  ├─ 근거 ≥ 2개 ──────► finalize    score_threshold 통과 청크만 RagResult에 포함
  │
  └─ 근거 부족  ──────► fallback_retrieve   필터 제거 + top_k×2로 재검색
                          │
                          └─────────────► finalize   1회 재시도 후 강제 종료
                                            │
                                           END
```

### 4.2 State 정의

```python
class RagState(TypedDict):
    question: str               # 검색 질문 (세션 지표 기반 자동 생성 또는 직접 입력)
    kiwi_keywords: list[str]    # Kiwi가 추출한 키워드
    expanded_keywords: list[str] # ontology 확장 후 키워드
    filters: dict               # language_area 등 메타데이터 필터
    evidence: list[RagEvidence] # 검색된 청크 목록 (score 포함)
    retry_count: int            # fallback 시도 횟수
    rag_result: RagResult | None # 최종 결과
```

### 4.3 노드별 역할

| 노드 | 역할 |
|---|---|
| `extract_keywords` | Kiwi로 질문에서 명사(`NNG`, `NNP`), 동사(`VV`), 형용사(`VA`) 추출 |
| `expand_query` | `semantic_layer.expand_query()`로 ontology 관련어 확장, `get_metadata_filters()`로 필터 생성 |
| `retrieve` | 원본 질문 + 확장 키워드를 KURE-v1으로 임베딩 → pgvector 검색 |
| `fallback_retrieve` | 메타데이터 필터 제거, `top_k * 2`로 범위 확대 후 재검색 |
| `finalize` | `score_threshold` 미만 청크 제거 → `RagResult` 생성 |

### 4.4 검색 파라미터

| 파라미터 | 기본값 | 설명 |
|---|---|---|
| `top_k` | 5 | 검색 결과 상위 k개 |
| `score_threshold` | 0.5 | 이 cosine similarity 미만 청크는 근거에서 제외 |
| fallback 조건 | `근거 < 2개` | 통과 청크가 2개 미만이면 재검색 |
| 최대 재시도 | 1회 | `retry_count >= 1`이면 강제 종료 |

---

## 5. Semantic Layer (쿼리 확장)

`semantic_layer.py`는 Kiwi 키워드와 `ontology.yaml` 개념 사전을 연결합니다.

### 5.1 ontology 구조 예시

```yaml
concepts:
  MLU:
    ko: "평균 발화 길이"
    related_terms:
      - "평균 발화 길이"
      - "형태소 수"
      - "발화 복잡도"
      - "표현언어"
    metrics:
      - "mlu_morpheme"
    language_area:
      - "expressive_language"

  MLU_formula:
    ko: "MLU 계산식"
    related_terms:
      - "총 형태소 수 / 총 발화 수"
      - "형태소 분절 방법"
      - "MLU-w"
      - "MLU-m"
      - "mean length of utterance"
    metrics:
      - "mlu_morpheme"
    language_area:
      - "expressive_language"

  TTR_formula:
    ko: "TTR 계산식"
    related_terms:
      - "NDW / NTW"
      - "어휘 다양도 계산"
      - "Type Token Ratio 공식"
      - "어휘 비율"
    metrics:
      - "ttr"
    language_area:
      - "vocabulary"
```

### 5.2 동작 방식

```
키워드: ["MLU", "발화"]
  └─ MLU → related_terms 전체 추가
  └─ 확장 결과: ["MLU", "발화", "평균 발화 길이", "형태소 수", "발화 복잡도", "표현언어"]
  └─ 메타데이터 필터: { language_area: ["expressive_language"], metric: ["mlu_morpheme"] }
```

---

## 6. 임베딩 모델

| 항목 | 내용 |
|---|---|
| 모델 | `nlpai-lab/KURE-v1` |
| 출력 차원 | 1024 |
| 라이브러리 | `sentence-transformers` |
| 정규화 | `normalize_embeddings=True` (cosine similarity 최적화) |
| 기본 디바이스 | CPU (문서 수가 많으면 `cuda`로 변경) |

---

## 7. Retriever 사용법

```python
from app.rag.retriever import Retriever
from app.schemas import RagQuery

retriever = Retriever(
    vector_store=vector_store,
    embedding_model=embedding_model,
    top_k=5,
    score_threshold=0.5,
)

query = RagQuery(
    question="MLU가 낮은 아동을 위한 표현언어 중재 활동은?",
    filters={"age_group": "preschool"},
)

rag_result = await retriever.retrieve(query)

for evidence in rag_result.evidence:
    print(f"[{evidence.score:.3f}] {evidence.title}: {evidence.text[:80]}")
```

---

## 8. 설계 결정 사항

### pgvector를 선택한 이유

별도 벡터 DB(Pinecone, Weaviate 등)를 추가하지 않고 기존 PostgreSQL에 pgvector 확장을 사용합니다. MVP 단계에서 인프라 복잡도를 낮추면서 관계형 메타데이터(세션, 문서 관계)와 벡터 검색을 한 곳에서 관리할 수 있습니다.

### LangGraph를 RAG에만 적용한 이유

VAD → STT → 정렬 파이프라인은 결정론적 선형 흐름이므로 단순 함수 호출로 충분합니다. RAG는 "검색 → 품질 판단 → 재검색" 루프가 필요하고, 나중에 도구(tool)를 추가하거나 human-in-the-loop 체크포인트를 삽입할 수 있어 LangGraph 그래프 구조가 적합합니다.

### fallback 전략

1차 검색에서 `score_threshold`를 통과한 청크가 2개 미만이면 메타데이터 필터를 제거하고 검색 범위를 넓혀 재시도합니다. 재시도는 1회로 제한해 무한 루프를 방지하고, 결과 품질과 무관하게 `finalize`로 강제 진행합니다.
