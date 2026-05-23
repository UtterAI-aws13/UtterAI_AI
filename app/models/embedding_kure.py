# KURE-v1 임베딩 모델 래퍼
# nlpai-lab/KURE-v1은 한국어 특화 임베딩 모델이다
# RAG 문서 청크와 검색 쿼리를 1024차원 벡터로 변환하고 pgvector에 저장/검색한다
from app.models.base import BaseModelWrapper


class KUREEmbeddingWrapper(BaseModelWrapper):
    """KURE-v1 한국어 임베딩 모델 래퍼.

    문서 ingest 시: 청크 텍스트 → 벡터 → pgvector 저장
    검색 시: 쿼리 텍스트 → 벡터 → pgvector cosine similarity 검색
    배치 입력을 지원해 대량 문서 ingest 시 GPU 처리 효율을 높인다.
    """
    def __init__(self, model_name: str, device: str = "cpu"):
        self.model_name = model_name
        self.device = device   # 문서 수가 많으면 cuda로 변경
        self.model = None

    def load(self) -> None:
        # TODO: sentence-transformers 또는 transformers 기반 KURE-v1 로드
        pass

    def predict(self, texts: list[str]) -> list[list[float]]:
        """텍스트 목록을 입력받아 각각의 1024차원 임베딩 벡터를 반환한다."""
        # TODO: 텍스트 배치 임베딩 반환
        return []

    def unload(self) -> None:
        self.model = None
