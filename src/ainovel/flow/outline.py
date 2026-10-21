"""从分层大纲推导弧边界。纯计算，供 LoadState 使用。"""

from ainovel.flow.model import ArcBoundary


def repair_indexes(volumes: list[dict]) -> list[dict]:
    repaired: list[dict] = []
    for volume_index, volume in enumerate(volumes, start=1):
        arcs = []
        for arc_index, arc in enumerate(volume.get("arcs") or [], start=1):
            copied = dict(arc)
            if int(copied.get("index") or 0) <= 0:
                copied["index"] = arc_index
            arcs.append(copied)
        copied_volume = dict(volume)
        if int(copied_volume.get("index") or 0) <= 0:
            copied_volume["index"] = volume_index
        copied_volume["arcs"] = arcs
        repaired.append(copied_volume)
    return repaired


def check_arc_boundary(volumes: list[dict], chapter: int) -> ArcBoundary | None:
    if not volumes or chapter <= 0:
        return None
    cursor = 1
    current = None
    for volume_pos, volume in enumerate(volumes):
        arcs = volume.get("arcs") or []
        for arc_pos, arc in enumerate(arcs):
            chapters = arc.get("chapters") or []
            arc_start = cursor
            for chapter_pos, _ in enumerate(chapters):
                if cursor == chapter:
                    current = {
                        "volume_pos": volume_pos,
                        "arc_pos": arc_pos,
                        "volume": int(volume.get("index") or 0),
                        "arc": int(arc.get("index") or 0),
                        "chapter_pos": chapter_pos,
                        "arc_len": len(chapters),
                        "arc_start": arc_start,
                    }
                cursor += 1
    if current is None:
        return None
    boundary = ArcBoundary(
        volume=current["volume"],
        arc=current["arc"],
        start_chapter=current["arc_start"],
        end_chapter=current["arc_start"] + current["arc_len"] - 1,
    )
    if current["chapter_pos"] != current["arc_len"] - 1:
        return boundary
    volume = volumes[current["volume_pos"]]
    arcs = volume.get("arcs") or []
    is_volume_end = current["arc_pos"] == len(arcs) - 1
    next_volume = 0
    next_arc = 0
    needs_expansion = False
    found = False
    for volume_pos in range(current["volume_pos"], len(volumes)):
        start_arc = current["arc_pos"] + 1 if volume_pos == current["volume_pos"] else 0
        later_arcs = volumes[volume_pos].get("arcs") or []
        for arc_pos in range(start_arc, len(later_arcs)):
            later = later_arcs[arc_pos]
            next_volume = int(volumes[volume_pos].get("index") or 0)
            next_arc = int(later.get("index") or 0)
            needs_expansion = len(later.get("chapters") or []) == 0
            found = True
            break
        if found:
            break
    return ArcBoundary(
        is_arc_end=True,
        is_volume_end=is_volume_end,
        volume=boundary.volume,
        arc=boundary.arc,
        start_chapter=boundary.start_chapter,
        end_chapter=boundary.end_chapter,
        next_volume=next_volume,
        next_arc=next_arc,
        needs_expansion=needs_expansion,
        needs_new_volume=is_volume_end and not found,
    )


def completed_arc_boundaries(volumes: list[dict], last_completed: int) -> list[ArcBoundary]:
    cursor = 1
    result: list[ArcBoundary] = []
    for volume in volumes:
        arcs = volume.get("arcs") or []
        for arc_pos, arc in enumerate(arcs):
            chapters = arc.get("chapters") or []
            if not chapters:
                continue
            start = cursor
            end = start + len(chapters) - 1
            cursor = end + 1
            if end > last_completed:
                return result
            result.append(
                ArcBoundary(
                    is_arc_end=True,
                    is_volume_end=arc_pos == len(arcs) - 1,
                    volume=int(volume.get("index") or 0),
                    arc=int(arc.get("index") or 0),
                    start_chapter=start,
                    end_chapter=end,
                )
            )
    return result
