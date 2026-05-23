from fastapi import APIRouter
from app.schemas import RagQuery, RagResult

router = APIRouter()


@router.post("/query", response_model=RagResult)
async def query_rag(request: RagQuery):
    # TODO: semantic layer -> retriever -> evidence 반환
    return RagResult(query=request.question, expanded_query=[], evidence=[])


@router.post("/ingest")
async def ingest_documents():
    # TODO: 문서 ingest 작업을 SQS에 발행
    return {"status": "accepted"}
