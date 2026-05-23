# RAG API
# POST /ai/rag/query  - 언어발달/치료 문서에서 관련 근거를 검색 (개발/테스트 용도)
# POST /ai/rag/ingest - 새 문서를 RAG 파이프라인에 등록 (청크 + 임베딩 + pgvector 저장)
from fastapi import APIRouter
from app.schemas import RagQuery, RagResult

router = APIRouter()


@router.post("/query", response_model=RagResult)
async def query_rag(request: RagQuery):
    """질문을 받아 ontology 확장 → KURE-v1 임베딩 → pgvector 검색 순으로 근거를 반환한다."""
    # TODO: semantic layer -> retriever -> evidence 반환
    return RagResult(query=request.question, expanded_query=[], evidence=[])


@router.post("/ingest")
async def ingest_documents():
    """문서 ingest 작업을 SQS에 발행한다. 실제 처리는 rag_ingest_worker가 담당한다."""
    # TODO: 문서 ingest 작업을 SQS에 발행
    return {"status": "accepted"}
