from app.models.base import BaseModelWrapper


class KUREEmbeddingWrapper(BaseModelWrapper):
    def __init__(self, model_name: str, device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self.model = None

    def load(self) -> None:
        # TODO: sentence-transformers 또는 transformers 기반 KURE-v1 로드
        pass

    def predict(self, texts: list[str]) -> list[list[float]]:
        # TODO: 텍스트 배치 임베딩 반환
        return []

    def unload(self) -> None:
        self.model = None
