from dataclasses import dataclass


@dataclass
class LoadedModel:
    name: str
    backend: str
    loaded: bool


def load_model(model_name: str) -> LoadedModel:
    """
    TODO:
    - 실제 HailoRT / hailo-apps pipeline 로 교체
    - HEF 로딩, input tensor shape 확인, pre/post-processing 연결
    """
    return LoadedModel(name=model_name, backend='hailo-skeleton', loaded=True)
