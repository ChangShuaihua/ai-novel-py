"""调度事实与纯函数路由。"""

from ainovel.flow.load import LoadStateError, foundation_missing, load_state
from ainovel.flow.model import Instruction, RouteState
from ainovel.flow.route import legal_moves, route

__all__ = [
    "Instruction",
    "LoadStateError",
    "RouteState",
    "foundation_missing",
    "legal_moves",
    "load_state",
    "route",
]
