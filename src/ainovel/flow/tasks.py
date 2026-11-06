"""路由职责对应的任务正文。route 只选择职责，句子集中在这里。"""


def fill_foundation(missing: list[str]) -> str:
    return (
        "补齐基础设定与作品信息缺项："
        + "、".join(missing)
        + "；book 使用 save_book，其余基础设定使用 save_foundation 落盘"
    )


def audit_foundation() -> str:
    return (
        "基础设定已齐全：重新调用 novel_context 读取全部已落盘工件与 "
        "foundation_status.fingerprint，审查跨文件语义一致性后调用 audit_foundation。"
        "有冲突则 ready=false 并给出 issues，改完工件后用新指纹再审；"
        "确认无冲突才 ready=true，此时才进入写作"
    )


def revise_chapter(chapter: int, *, polish: bool) -> str:
    verb = "打磨" if polish else "重写"
    return f"{verb}第 {chapter} 章"


def outline_feedback() -> str:
    return (
        "仅处理 novel_context 中的外部修订 writer_feedback：核对已发生剧情与后续计划，"
        "需要调整时调用 revise_outline 或相应结构工具，无需调整时调用 resolve_outline_feedback；"
        "不得处理 foundation_status 或其它规划，落盘后用一句话结束"
    )


def arc_review(volume: int, arc: int, start: int, end: int) -> str:
    return (
        f"对第 {volume} 卷第 {arc} 弧"
        f"（第 {start}-{end} 章）做弧级评审："
        f"调用 novel_context(chapter={end})，"
        f"save_review 使用 scope=arc、chapter={end}；"
        "issues[].chapters 只能落在该区间"
    )


def arc_review_refresh(volume: int, arc: int, start: int, end: int) -> str:
    return (
        f"审阅第 {volume} 卷第 {arc} 弧"
        f"（第 {start}-{end} 章）："
        f"调用 novel_context(chapter={end})，"
        f"save_review 使用 scope=arc、chapter={end}"
    )


def arc_summary(volume: int, arc: int) -> str:
    return f"生成第 {volume} 卷第 {arc} 弧摘要、角色快照与写作规则（save_arc_summary）"


def volume_summary(volume: int) -> str:
    return f"生成第 {volume} 卷卷摘要（save_volume_summary）"


def expand_arc(volume: int, arc: int) -> str:
    return f"展开第 {volume} 卷第 {arc} 弧（expand_next_arc）"


def new_volume() -> str:
    return (
        "创建下一卷：按完结判定清单评估后调用 save_foundation——"
        "故事继续 → type=append_volume；故事接近终点 → type=append_volume 且卷 JSON 顶层带 "
        '"final": true（收官卷，整卷收线，写完自动完结）；'
        "全部完结条件当下已满足 → type=complete_book。三选一均须附 reason 参数写明判定理由"
    )


def global_review(chapter: int) -> str:
    return f"对前 {chapter} 章做全局审阅（save_review scope=global, chapter={chapter}）"


def global_review_refresh(chapter: int) -> str:
    return (
        f"审阅前 {chapter} 章：调用 novel_context(chapter={chapter})，"
        f"save_review 使用 scope=global、chapter={chapter}"
    )


def outline_exhausted(completed: int, total: int, next_chapter: int) -> str:
    return (
        f"非分层大纲已写完（已完成 {completed} 章，共 {total} 章）："
        "若故事已收束，调用 save_foundation(type=complete_book)；"
        f"若仍需继续，用 revise_outline 从第 {next_chapter} 章续接后续计划"
    )


def write_chapter(chapter: int) -> str:
    return f"写第 {chapter} 章"
