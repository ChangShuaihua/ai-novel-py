"""把提供方异常收成稳定的种类。"""

from ainovel.llm.errors import ProviderError

_AUTH = {"authenticationerror", "permissiondeniederror"}
_RATE = {"ratelimiterror"}
_UNAVAILABLE = {"serviceunavailableerror"}
_NOT_FOUND = {"notfounderror"}
_TIMEOUT = {"timeouterror", "apitimeouterror"}


def classify_exception(exc: BaseException) -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc
    status = getattr(exc, "status_code", None)
    status_code = status if isinstance(status, int) else None
    name = type(exc).__name__.lower()
    if status_code in (401, 403) or name in _AUTH:
        kind = "auth"
    elif status_code == 404 or name in _NOT_FOUND:
        kind = "model_not_found"
    elif status_code == 429 or name in _RATE:
        kind = "rate_limit"
    elif status_code == 503 or name in _UNAVAILABLE:
        kind = "unavailable"
    elif status_code == 408 or name in _TIMEOUT:
        kind = "timeout"
    elif status_code in (502, 504) or "stream" in name:
        kind = "stream_interrupted"
    else:
        kind = "unknown"
    retry_after = getattr(exc, "retry_after", None)
    if not isinstance(retry_after, (int, float)):
        retry_after = None
    return ProviderError(str(exc), kind=kind, status=status_code, retry_after=retry_after)
