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
    def __init__(self, model_name: str, device: str = "cuda", max_new_tokens: int = 1024):
        self.model_name = model_name
        self.device = device
        self.max_new_tokens = max_new_tokens
        self.model = None
        self.tokenizer = None

    def load(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            torch_dtype=torch.bfloat16 if self.device != "cpu" else torch.float32,
            device_map=self.device,
        )
        self.model.eval()

    def predict(self, prompt: str) -> str:
        """프롬프트를 입력받아 LLM이 생성한 raw 텍스트를 반환한다."""
        import torch

        if self.model is None:
            self.load()

        messages = [{"role": "user", "content": prompt}]
        input_ids = self.tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
        ).to(self.model.device)

        with torch.no_grad():
            output_ids = self.model.generate(
                input_ids,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                eos_token_id=self.tokenizer.eos_token_id,
            )

        # 입력 토큰 이후 생성된 부분만 디코딩
        generated = output_ids[0][input_ids.shape[-1]:]
        return self.tokenizer.decode(generated, skip_special_tokens=True)

    def unload(self) -> None:
        self.model = None
        self.tokenizer = None
