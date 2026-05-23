# EXAONE LLM 모델 래퍼
# LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct 사용, GPU 권장
# RAG 검색 근거와 언어 지표를 바탕으로 SOAP Note 초안 JSON을 생성한다
from app.models.base import BaseModelWrapper


class EXAONEWrapper(BaseModelWrapper):
    """EXAONE 3.5 2.4B 인스트럭트 모델 래퍼.

    predict()는 raw 텍스트(JSON 문자열)를 반환한다.
    JSON 파싱 및 schema 검증은 report_pipeline에서 처리한다.
    프롬프트에 JSON schema와 안전 지침(진단 확정 금지)을 명시해야 한다.
    """
    def __init__(self, model_name: str, device: str = "cuda"):
        self.model_name = model_name
        self.device = device
        self.model = None
        self.tokenizer = None

    def load(self) -> None:
        # TODO: transformers AutoModelForCausalLM + AutoTokenizer 로드
        pass

    def predict(self, prompt: str) -> str:
        """프롬프트를 입력받아 LLM이 생성한 raw 텍스트를 반환한다."""
        # TODO: LLM 추론 후 raw 텍스트 반환 (JSON 파싱은 report_pipeline에서)
        return ""

    def unload(self) -> None:
        self.model = None
        self.tokenizer = None
