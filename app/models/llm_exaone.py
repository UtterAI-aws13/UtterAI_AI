from app.models.base import BaseModelWrapper
from app.schemas import ReportDraft


class EXAONEWrapper(BaseModelWrapper):
    def __init__(self, model_name: str, device: str = "cuda"):
        self.model_name = model_name
        self.device = device
        self.model = None
        self.tokenizer = None

    def load(self) -> None:
        # TODO: transformers AutoModelForCausalLM 로드
        pass

    def predict(self, prompt: str) -> str:
        # TODO: LLM 추론 후 raw 텍스트 반환 (JSON 파싱은 report_pipeline에서)
        return ""

    def unload(self) -> None:
        self.model = None
        self.tokenizer = None
