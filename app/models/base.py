# 모든 AI 모델 래퍼의 추상 기반 클래스
# 각 모델(VAD, ASR, 화자분리, 임베딩, LLM)은 이 인터페이스를 구현해야 한다
# 파이프라인 코드가 모델 구현체에 직접 의존하지 않도록 인터페이스를 통일한다
from abc import ABC, abstractmethod
from typing import Any


class BaseModelWrapper(ABC):
    """AI 모델 래퍼 공통 인터페이스.

    load()  : 모델을 메모리에 로드한다 (Worker 시작 시 한 번만 호출)
    predict(): 입력을 받아 추론 결과를 반환한다
    unload(): 모델을 메모리에서 해제한다 (GPU 메모리 절약 목적)
    """
    model_name: str

    @abstractmethod
    def load(self) -> None:
        pass

    @abstractmethod
    def predict(self, input_data: Any) -> Any:
        pass

    def unload(self) -> None:
        pass
