"""模型引用和一次补全的结果。不含小说业务。"""

from pydantic import BaseModel, Field


class ModelRef(BaseModel):
    provider: str
    model: str
    api_key: str = ""
    api_base: str = ""

    def litellm_model(self) -> str:
        if not self.provider or "/" in self.model:
            return self.model
        return f"{self.provider}/{self.model}"


class RoleModel(BaseModel):
    primary: ModelRef
    fallbacks: list[ModelRef] = Field(default_factory=list)


class ToolSpec(BaseModel):
    name: str
    description: str = ""
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})

    def to_openai(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _sort_keys(self.parameters),
            },
        }


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str = ""


class Completion(BaseModel):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: str = ""


def _sort_keys(value):
    if isinstance(value, dict):
        return {key: _sort_keys(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sort_keys(item) for item in value]
    return value
