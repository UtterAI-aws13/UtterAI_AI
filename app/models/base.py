from abc import ABC, abstractmethod
from typing import Any


class BaseModelWrapper(ABC):
    model_name: str

    @abstractmethod
    def load(self) -> None:
        pass

    @abstractmethod
    def predict(self, input_data: Any) -> Any:
        pass

    def unload(self) -> None:
        pass
