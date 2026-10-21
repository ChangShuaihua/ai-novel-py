"""逐章验收和一次性暂停。不进路由，也不解释任务文案。"""

from ainovel.domain.checkpoint import chapter_scope
from ainovel.domain.errors import UnsupportedAdvanceModeError
from ainovel.domain.run_meta import AdvanceHoldAfter, advance_mode_supported
from ainovel.flow.advance import CONSUME, CONSUME_AND_STOP, resolve_advance_hold, starts_forward_chapter
from ainovel.flow.model import Instruction
from ainovel.store.book import Book


class ChapterAdvanceGate:
    def __init__(self, book: Book, pause) -> None:
        self.book = book
        self.pause = pause

    def handle_boundary(self) -> bool:
        meta = self.book.run_meta.load()
        if meta is None:
            return False
        if not advance_mode_supported(meta.advance_mode):
            return self._fail(UnsupportedAdvanceModeError(meta.advance_mode))
        if meta.advance_mode == "auto" and meta.advance_permit_chapter:
            return self._fail(ValueError(f"auto 模式残留第 {meta.advance_permit_chapter} 章许可"))
        if meta.advance_hold is not None and self._handle_hold(meta.advance_hold):
            return True
        if meta.advance_mode == "auto":
            return False
        meta = self.book.run_meta.load() or meta
        return self._reconcile_permit(meta.advance_permit_chapter)

    def allow(self, instruction: Instruction) -> bool:
        meta = self.book.run_meta.load()
        if meta is None:
            return True
        if not advance_mode_supported(meta.advance_mode):
            self._fail(UnsupportedAdvanceModeError(meta.advance_mode))
            return False
        if meta.advance_mode == "auto":
            if meta.advance_permit_chapter:
                self._fail(ValueError(f"auto 模式残留第 {meta.advance_permit_chapter} 章许可"))
                return False
            return True
        progress = self.book.progress.load()
        pending = self.book.pending.load()
        if not starts_forward_chapter(instruction, progress, pending):
            return True
        target = instruction.chapter or (progress.next_chapter() if progress is not None else 0)
        if meta.advance_permit_chapter == target:
            return True
        if meta.advance_permit_chapter:
            self._fail(ValueError(f"第 {target} 章派发与第 {meta.advance_permit_chapter} 章许可不一致"))
            return False
        hold = meta.advance_hold
        if hold is not None and hold.after == AdvanceHoldAfter.CHAPTER and target <= hold.target_chapter:
            return True
        latest = progress.latest_completed() if progress is not None else 0
        if latest == 0:
            message = f"规划已就绪，逐章验收等待放行第 {target} 章；使用 /next 生成，或输入修改意见"
        else:
            message = f"已完成至第 {latest} 章，逐章验收等待放行第 {target} 章；使用 /next 生成，或输入修改意见"
        self.pause(message)
        return False

    def _handle_hold(self, hold) -> bool:
        progress = self.book.progress.load()
        try:
            resolution = resolve_advance_hold(hold, progress)
        except ValueError as exc:
            return self._fail(exc)
        if hold.after == AdvanceHoldAfter.CHAPTER and progress is not None and progress.latest_completed() >= hold.target_chapter:
            stable, error = self._target_committed(progress, hold.target_chapter)
            if error is not None:
                return self._fail(error)
            if not stable:
                return False
        if resolution == CONSUME:
            self.book.run_meta.clear_advance_hold(hold)
            return False
        if resolution == CONSUME_AND_STOP:
            self.book.run_meta.clear_advance_hold(hold)
            if hold.after == AdvanceHoldAfter.REWRITES_DRAINED:
                message = "返工队列已排空，已暂停等待验收"
            elif hold.after == AdvanceHoldAfter.CHAPTER:
                message = f"已写到第 {hold.target_chapter} 章，按用户要求暂停"
            else:
                message = "已按用户要求在当前工作边界暂停"
            if hold.reason:
                message = f"{message}（诉求：{hold.reason}）"
            self.pause(message)
            return True
        return False

    def _reconcile_permit(self, permit: int) -> bool:
        if permit == 0:
            return False
        if permit < 0:
            return self._fail(ValueError(f"章节许可不能为负数: {permit}"))
        progress = self.book.progress.load()
        if progress is None:
            return self._fail(ValueError(f"缺少 Progress，无法对账第 {permit} 章许可"))
        pending = self.book.pending.load()
        completed = permit in progress.completed_chapters
        if completed:
            if pending is not None:
                if pending.chapter != permit:
                    return self._fail(ValueError(f"第 {permit} 章许可与第 {pending.chapter} 章 PendingCommit 冲突"))
                return False
            if not _has_commit(self.book, permit):
                return self._fail(ValueError(f"第 {permit} 章已标记完成但缺少 commit checkpoint"))
            self.book.run_meta.clear_advance_permit(permit)
            return False
        if permit != progress.next_chapter():
            return self._fail(ValueError(f"第 {permit} 章许可与当前下一章 {progress.next_chapter()} 不一致"))
        return False

    def _target_committed(self, progress, chapter: int) -> tuple[bool, Exception | None]:
        pending = self.book.pending.load()
        if pending is not None:
            return False, None
        if chapter not in progress.completed_chapters:
            return False, ValueError(f"目标第 {chapter} 章未出现在已完成章节中")
        if not _has_commit(self.book, chapter):
            return False, ValueError(f"目标第 {chapter} 章已标记完成但缺少 commit checkpoint")
        return True, None

    def _fail(self, exc: Exception) -> bool:
        self.pause("章节推进控制错误，已暂停：" + str(exc))
        return True


def _has_commit(book: Book, chapter: int) -> bool:
    scope = chapter_scope(chapter)
    return any(item.scope.matches(scope) and item.step == "commit" for item in book.checkpoints.all())
