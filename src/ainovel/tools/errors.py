"""工具层可预期的失败。"""


class ToolArgsError(ValueError):
    """参数非法。调用方应修改参数后重试。"""


class ToolConflict(ValueError):
    """缺前置工件、阶段冲突，或在途提交对不上。"""
