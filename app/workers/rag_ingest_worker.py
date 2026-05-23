# RAG 문서 ingest Worker
# SQS에서 ingest 요청 메시지를 수신해 문서를 chunk → embedding → pgvector 저장한다
# 분석 Worker와 별도로 운영해 RAG 문서 업데이트가 분석 파이프라인에 영향을 주지 않게 한다


def handle_ingest_message(message: dict) -> None:
    """ingest 메시지를 받아 문서 처리 파이프라인을 실행한다.

    처리 순서:
    1. S3에서 원본 문서 다운로드
    2. 문서 파싱 (PDF, Markdown 등)
    3. 의미 단위 chunking (300~700 tokens, 50~100 tokens overlap)
    4. KURE-v1 임베딩 생성
    5. ChunkMetadata와 함께 pgvector 저장
    """
    # TODO: 문서 S3 다운로드 -> 파싱 -> chunk -> 임베딩 -> pgvector 저장
    raise NotImplementedError


def start_worker() -> None:
    """SQS 큐를 폴링하며 ingest 메시지를 처리하는 루프."""
    # TODO: SQS 폴링 루프
    raise NotImplementedError
