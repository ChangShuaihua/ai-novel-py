"""三个代理的工具表。多出来的名字不会被放进对应代理。"""

from ainovel.llm.types import ToolSpec

ARCHITECT_TOOLS = (
    "novel_context",
    "save_book",
    "save_foundation",
    "audit_foundation",
    "expand_next_arc",
    "revise_outline",
    "resolve_outline_feedback",
)
WRITER_TOOLS = (
    "novel_context",
    "read_chapter",
    "plan_chapter",
    "draft_chapter",
    "edit_chapter",
    "check_consistency",
    "commit_chapter",
)
EDITOR_TOOLS = (
    "novel_context",
    "read_chapter",
    "save_review",
    "save_arc_summary",
    "save_volume_summary",
)

ARCHITECT_STOP = (
    "save_book",
    "save_foundation",
    "audit_foundation",
    "expand_next_arc",
    "revise_outline",
    "resolve_outline_feedback",
)
WRITER_STOP = ("commit_chapter",)
EDITOR_STOP = ("save_review", "save_arc_summary", "save_volume_summary")

ARCHITECT_STEPS = (
    "book",
    "premise",
    "outline",
    "layered_outline",
    "characters",
    "world_rules",
    "foundation_audit",
    "expand_next_arc",
    "append_volume",
    "update_compass",
    "complete_book",
    "resolve_outline_feedback",
)
WRITER_STEPS = ("commit",)

_SPECS: dict[str, ToolSpec] = {
    "novel_context": ToolSpec(
        name="novel_context",
        description="读取当前任务需要的书籍事实。",
        parameters={"type": "object", "properties": {"chapter": {"type": "integer"}}, "required": []},
    ),
    "read_chapter": ToolSpec(
        name="read_chapter",
        description="读取已提交的章节正文。",
        parameters={"type": "object", "properties": {"chapter": {"type": "integer"}}, "required": ["chapter"]},
    ),
    "save_book": ToolSpec(
        name="save_book",
        description="保存书名和简介。",
        parameters={
            "type": "object",
            "properties": {"title": {"type": "string"}, "synopsis": {"type": "string"}},
            "required": ["title", "synopsis"],
        },
    ),
    "save_foundation": ToolSpec(
        name="save_foundation",
        description="保存设定。type 只能是封闭枚举里的一种。",
        parameters={
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "content": {},
                "scale": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["type"],
        },
    ),
    "audit_foundation": ToolSpec(
        name="audit_foundation",
        description="设定文件齐全后记下审查结果。",
        parameters={"type": "object", "properties": {"notes": {"type": "string"}}, "required": []},
    ),
    "expand_next_arc": ToolSpec(
        name="expand_next_arc",
        description="展开下一根骨架弧。",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "goal": {"type": "string"},
                "chapters": {"type": "array"},
            },
            "required": ["title", "goal", "chapters"],
        },
    ),
    "revise_outline": ToolSpec(
        name="revise_outline",
        description="按外部修订改正后续大纲。",
        parameters={"type": "object", "properties": {"content": {"type": "array"}}, "required": ["content"]},
    ),
    "resolve_outline_feedback": ToolSpec(
        name="resolve_outline_feedback",
        description="确认这批外部修订不必改大纲。",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    "plan_chapter": ToolSpec(
        name="plan_chapter",
        description="写入本章计划。",
        parameters={
            "type": "object",
            "properties": {
                "chapter": {"type": "integer"},
                "goal": {"type": "string"},
                "conflict": {"type": "string"},
                "emotion": {"type": "string"},
                "characters": {"type": "array"},
            },
            "required": ["chapter", "goal"],
        },
    ),
    "draft_chapter": ToolSpec(
        name="draft_chapter",
        description="整章覆盖草稿。",
        parameters={
            "type": "object",
            "properties": {"chapter": {"type": "integer"}, "content": {"type": "string"}},
            "required": ["chapter", "content"],
        },
    ),
    "edit_chapter": ToolSpec(
        name="edit_chapter",
        description="修改返工队列队首的已完成章节。",
        parameters={
            "type": "object",
            "properties": {"chapter": {"type": "integer"}, "content": {"type": "string"}},
            "required": ["chapter", "content"],
        },
    ),
    "check_consistency": ToolSpec(
        name="check_consistency",
        description="对照已落盘的草稿做一致性检查。",
        parameters={"type": "object", "properties": {"chapter": {"type": "integer"}}, "required": ["chapter"]},
    ),
    "commit_chapter": ToolSpec(
        name="commit_chapter",
        description="提交本章终稿。",
        parameters={
            "type": "object",
            "properties": {
                "chapter": {"type": "integer"},
                "summary": {"type": "string"},
                "hook_type": {"type": "string"},
                "dominant_strand": {"type": "string"},
            },
            "required": ["chapter", "summary"],
        },
    ),
    "save_review": ToolSpec(
        name="save_review",
        description="保存审阅结论。",
        parameters={
            "type": "object",
            "properties": {
                "chapter": {"type": "integer"},
                "scope": {"type": "string"},
                "verdict": {"type": "string"},
                "summary": {"type": "string"},
                "issues": {"type": "array"},
            },
            "required": ["chapter", "verdict", "summary"],
        },
    ),
    "save_arc_summary": ToolSpec(
        name="save_arc_summary",
        description="保存弧摘要。",
        parameters={
            "type": "object",
            "properties": {
                "volume": {"type": "integer"},
                "arc": {"type": "integer"},
                "summary": {"type": "string"},
            },
            "required": ["volume", "arc", "summary"],
        },
    ),
    "save_volume_summary": ToolSpec(
        name="save_volume_summary",
        description="保存卷摘要。",
        parameters={
            "type": "object",
            "properties": {"volume": {"type": "integer"}, "summary": {"type": "string"}},
            "required": ["volume", "summary"],
        },
    ),
}


def specs_for(names: tuple[str, ...]) -> tuple[ToolSpec, ...]:
    return tuple(_SPECS[name] for name in names)
