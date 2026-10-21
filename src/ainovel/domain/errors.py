"""领域层可预期的失败。"""


class PhaseTransitionError(ValueError):
    """阶段迁移违反只前进规则。"""


class FlowTransitionError(ValueError):
    """流程跳转不在允许表内。"""


class UnsupportedAdvanceModeError(ValueError):
    """书籍使用了当前版本不认识的章节推进模式。"""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        super().__init__(
            f"不支持的章节推进模式 {mode!r}，请使用创建该项目的新版 ainovel"
        )
