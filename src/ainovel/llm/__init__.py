"""模型适配。循环和小说工具不在这一层。"""

from ainovel.llm.errors import ProviderError
from ainovel.llm.litellm_client import LiteLLMTransport
from ainovel.llm.policy import RoleClient
from ainovel.llm.types import Completion, ModelRef, RoleModel, ToolCall, ToolSpec

__all__ = [
    "Completion",
    "LiteLLMTransport",
    "ModelRef",
    "ProviderError",
    "RoleClient",
    "RoleModel",
    "ToolCall",
    "ToolSpec",
]
