"""章节文件名：1–9 补零，100 以上按自然宽度。"""


def chapter_number(chapter: int) -> str:
    if chapter <= 0:
        raise ValueError("章节号必须大于 0")
    return f"{chapter:02d}"
