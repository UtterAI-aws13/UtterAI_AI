# 데이터베이스 설정 가이드

---

## 1. 현재 구현 상태 요약

```
코드 구현 완료 (직접 건드릴 필요 없음)
  ├── app/storage/db.py          SQLAlchemy async 엔진 + 세션 설정
  └── app/rag/vector_store.py    RagChunkORM 테이블 정의 + upsert / search

직접 준비해야 하는 것
  ├── PostgreSQL 인스턴스 실행    (로컬: Docker / 운영: AWS RDS)
  ├── pgvector 확장 활성화        CREATE EXTENSION vector
  └── 테이블 생성                 scripts/init_db.sql 또는 create_tables.py 실행
```

코드는 SQLAlchemy ORM으로 테이블 구조를 정의해 놓았습니다.
실제 데이터베이스 인스턴스를 띄우고 테이블을 만드는 작업은 아래 절차를 따릅니다.

---

## 2. 왜 pgvector인가

일반 PostgreSQL은 벡터 데이터를 저장하거나 cosine similarity 검색을 할 수 없습니다.
pgvector는 PostgreSQL 확장(Extension)으로, 다음을 추가합니다.

- `VECTOR(n)` 타입 — n차원 실수 벡터를 컬럼에 저장
- `<=>` 연산자 — cosine distance 계산
- IVFFlat / HNSW 인덱스 — 대량 벡터의 빠른 근사 검색(ANN)

UtterAI는 KURE-v1이 생성하는 **1024차원 벡터**를 `rag_chunks.embedding` 컬럼에 저장하고,
치료 문서 검색 시 cosine similarity로 가장 관련 있는 청크를 찾습니다.

별도 벡터 DB(Pinecone, Weaviate 등)를 추가하지 않고 PostgreSQL 하나로 관계형 데이터와
벡터 검색을 함께 처리해 MVP 단계의 인프라 복잡도를 낮춥니다.

---

## 3. 로컬 개발 환경 설정

### 3.1 Docker로 PostgreSQL + pgvector 실행 (권장)

`pgvector/pgvector:pg16` 이미지는 pgvector가 미리 설치된 공식 이미지입니다.
별도 설치 없이 컨테이너 하나로 바로 사용할 수 있습니다.

```bash
# PostgreSQL 컨테이너 시작
docker compose up -d

# 컨테이너 상태 확인
docker compose ps

# 로그 확인
docker compose logs postgres
```

`docker-compose.yml`이 실행되면 다음이 자동으로 처리됩니다.

1. `pgvector/pgvector:pg16` 이미지 다운로드
2. `utterai_ai` 데이터베이스 생성
3. `scripts/init_db.sql` 자동 실행
   - `CREATE EXTENSION vector` — pgvector 활성화
   - `rag_chunks` 테이블 생성
   - cosine similarity 인덱스 생성

### 3.2 연결 확인

```bash
# psql 직접 접속
docker exec -it utterai_postgres psql -U utterai -d utterai_ai

# pgvector 확장 확인
\dx

# 테이블 확인
\dt

# rag_chunks 컬럼 확인
\d rag_chunks
```

정상 설치 시 출력 예시:

```
                  List of installed extensions
  Name   | Version |   Schema   |         Description
---------+---------+------------+------------------------------
 vector  | 0.7.0   | public     | vector data type and ivfflat access method

                List of relations
 Schema |    Name    | Type  |  Owner
--------+------------+-------+---------
 public | rag_chunks | table | utterai

                        Table "public.rag_chunks"
    Column     |     Type      | Nullable |      Default
---------------+---------------+----------+-------------------
 chunk_id      | text          | not null |
 document_id   | text          | not null |
 content       | text          | not null |
 embedding     | vector(1024)  | not null |
 metadata_json | jsonb         | not null | '{}'::jsonb
```

### 3.3 .env 설정

`.env.example`을 복사해서 `.env`를 만들고 DATABASE_URL을 설정합니다.

```env
DATABASE_URL=postgresql+psycopg://utterai:utterai@localhost:5432/utterai_ai
```

드라이버 설명:

| 드라이버 | 패키지 | 비고 |
|---|---|---|
| `postgresql+psycopg` | `psycopg[binary]` | async 지원, 권장 |
| `postgresql+asyncpg` | `asyncpg` | 대안 |

---

## 4. 테이블 구조

### 4.1 rag_chunks

RAG 파이프라인에서 사용하는 유일한 테이블입니다.

```sql
CREATE TABLE rag_chunks (
    chunk_id      TEXT PRIMARY KEY,       -- "{document_id}_chunk_{0000}" 형식
    document_id   TEXT        NOT NULL,   -- 원본 문서 ID
    content       TEXT        NOT NULL,   -- 청크 텍스트 원문
    embedding     VECTOR(1024) NOT NULL,  -- KURE-v1이 생성한 1024차원 벡터
    metadata_json JSONB       NOT NULL    -- ChunkMetadata 직렬화
);
```

`metadata_json` 저장 예시:

```json
{
  "document_id": "doc_001",
  "chunk_id": "doc_001_chunk_0003",
  "title": "언어발달 평가 가이드",
  "source_type": "clinical_guide",
  "age_group": "preschool",
  "language_area": "expressive_language",
  "metric": ["mlu_morpheme", "ndw"],
  "page": 12,
  "section": "3.2 표현언어 평가"
}
```

### 4.2 인덱스

```sql
-- document_id 기준 필터 조회 (특정 문서의 청크만 조회할 때)
CREATE INDEX idx_rag_chunks_document_id ON rag_chunks (document_id);

-- cosine similarity 검색용 IVFFlat 인덱스
-- lists: 전체 청크 수 / 100 으로 설정 (청크 10,000개 → lists=100)
CREATE INDEX idx_rag_chunks_embedding
    ON rag_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

IVFFlat 인덱스는 **정확한 검색** 대신 **빠른 근사 검색(ANN)**을 제공합니다.
청크가 1,000개 미만인 경우 인덱스 없이도 full scan이 빠릅니다.

---

## 5. 코드와 DB의 관계

```
app/storage/db.py
  └─ engine, Base 정의 (SQLAlchemy async 엔진)

app/rag/vector_store.py
  ├─ RagChunkORM(Base)        ← rag_chunks 테이블을 Python 클래스로 표현
  └─ VectorStore
       ├─ upsert()            ← session.merge() → INSERT OR UPDATE
       └─ search()            ← cosine_distance() → ORDER BY → LIMIT
```

`VectorStore`는 SQLAlchemy `AsyncSession`을 생성자에서 받습니다.
FastAPI dependency injection 또는 Worker에서 세션을 주입해 사용합니다.

```python
from app.storage.db import get_session
from app.rag.vector_store import VectorStore

# FastAPI endpoint 예시
async def rag_ingest(session: AsyncSession = Depends(get_session)):
    vector_store = VectorStore(session)
    await vector_store.upsert(chunks, embeddings)
```

---

## 6. Docker 없이 직접 PostgreSQL을 사용하는 경우

이미 PostgreSQL이 설치돼 있다면 pgvector를 수동으로 설치해야 합니다.

### Ubuntu / Debian

```bash
sudo apt install postgresql-16-pgvector
```

### macOS (Homebrew)

```bash
brew install pgvector
```

설치 후 psql에서 확장을 활성화합니다.

```sql
-- utterai_ai 데이터베이스에 접속 후 실행
CREATE EXTENSION vector;
```

테이블은 Python 스크립트로 생성합니다.

```bash
python scripts/create_tables.py
```

---

## 7. 운영 환경 — AWS RDS

### 7.1 RDS 설정

AWS RDS for PostgreSQL은 버전 15 이상에서 pgvector를 기본 지원합니다.
별도 설치 없이 아래 명령어만 실행하면 됩니다.

```sql
CREATE EXTENSION vector;
```

권장 설정:

| 항목 | 권장값 | 이유 |
|---|---|---|
| 엔진 버전 | PostgreSQL 16 | pgvector 0.7+ 지원 |
| 인스턴스 | db.t3.medium (Dev) / db.r6g.large (운영) | RAG 검색 쿼리는 메모리를 많이 사용 |
| 스토리지 | gp3 20GB~ | 임베딩 벡터 크기: 청크 1만 개 × 1024차원 × 4byte ≈ 40MB |
| Multi-AZ | Dev: 비활성 / 운영: 활성 | |

### 7.2 연결 설정

```env
# 운영 환경 .env (Secrets Manager 또는 EKS Secret으로 주입)
DATABASE_URL=postgresql+psycopg://utterai:PASSWORD@utterai-db.xxx.rds.amazonaws.com:5432/utterai_ai
```

### 7.3 테이블 생성 (운영 최초 1회)

```bash
# ECS Task 또는 EC2에서 실행
python scripts/create_tables.py

# 또는 RDS에 직접 접속해 SQL 실행
psql $DATABASE_URL -f scripts/init_db.sql
```

---

## 8. 로컬 개발 빠른 시작 요약

```bash
# 1. PostgreSQL + pgvector 컨테이너 시작
docker compose up -d

# 2. .env 설정
cp .env.example .env
# DATABASE_URL=postgresql+psycopg://utterai:utterai@localhost:5432/utterai_ai

# 3. Python 패키지 설치
pip install -r requirements.txt

# 4. 연결 확인 (테이블은 docker-compose 실행 시 자동 생성됨)
docker exec -it utterai_postgres psql -U utterai -d utterai_ai -c "\dt"

# 5. API 실행
uvicorn app.main:app --reload
```
