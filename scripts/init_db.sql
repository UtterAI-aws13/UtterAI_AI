-- UtterAI AI DB 초기화 스크립트
-- docker-compose 최초 실행 시 자동으로 실행된다
-- 직접 실행할 경우: psql -U utterai -d utterai_ai -f scripts/init_db.sql

-- pgvector 확장 활성화 (vector 타입 사용에 필요)
CREATE EXTENSION IF NOT EXISTS vector;

-- RAG 청크 테이블
-- KURE-v1이 생성한 1024차원 임베딩을 embedding 컬럼에 저장
CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id      TEXT PRIMARY KEY,
    document_id   TEXT        NOT NULL,
    content       TEXT        NOT NULL,
    embedding     VECTOR(1024) NOT NULL,
    metadata_json JSONB       NOT NULL DEFAULT '{}'
);

-- document_id 기준 필터 조회용 인덱스
CREATE INDEX IF NOT EXISTS idx_rag_chunks_document_id
    ON rag_chunks (document_id);

-- cosine similarity 검색용 IVFFlat 인덱스
-- lists 값은 저장된 청크 수 / 100 기준으로 조정 (청크 1만 개 → lists=100)
CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding
    ON rag_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
