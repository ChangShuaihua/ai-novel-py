const PHASES = ["init", "premise", "outline", "writing", "complete"]
const MARK_LIMIT = 36

export function progressView(snapshot = {}) {
  const phase = snapshot.phase || ""
  const index = PHASES.indexOf(phase)
  const completed = Array.isArray(snapshot.completed_chapters) ? snapshot.completed_chapters : []
  const done = new Set(completed.map(Number).filter((n) => n > 0))
  const rewrites = new Set((snapshot.pending_rewrites || []).map(Number).filter((n) => n > 0))
  const total = Math.max(0, Number(snapshot.total_chapters) || 0)
  const next = Math.max(0, Number(snapshot.next_chapter) || 0)
  const words = Math.max(0, Number(snapshot.total_word_count) || 0)
  const written = total > 0 ? [...done].filter((n) => n <= total).length : done.size
  const beyond = total > 0 ? [...done].filter((n) => n > total).sort((a, b) => a - b) : []
  const phases = PHASES.map((id, i) => ({
    id,
    state: index < 0 ? "ahead" : i < index ? "done" : i === index ? "current" : "ahead",
  }))
  const marks = total > 0 && total <= MARK_LIMIT
    ? Array.from({ length: total }, (_, offset) => {
      const n = offset + 1
      let state = "wait"
      if (rewrites.has(n)) state = "rewrite"
      else if (done.has(n)) state = "done"
      else if (phase === "writing" && n === next) state = "current"
      return { n, state }
    })
    : null
  return { phases, phase, total, written, beyond, words, marks, ratio: total > 0 ? written / total : 0 }
}

export function progressCaption(view, flow) {
  if (!view.phase && view.total === 0 && view.written === 0) return "还没有进度"
  const beyond = view.beyond || []
  const latestBeyond = beyond.length ? beyond[beyond.length - 1] : 0
  const chapters = latestBeyond && view.written >= view.total
    ? `大纲 ${view.total} 章已写完 · 又写到第 ${latestBeyond} 章`
    : latestBeyond
      ? `已完成 ${view.written} / 共 ${view.total} 章 · 大纲外写到第 ${latestBeyond} 章`
      : view.total > 0
        ? `已完成 ${view.written} / 共 ${view.total} 章`
        : view.written > 0
          ? `已完成 ${view.written} 章`
          : "章数还没定"
  const parts = [chapters]
  if (view.words > 0) parts.push(`${formatWords(view.words)} 字`)
  if (flow && view.phase === "writing") parts.push(flow)
  return parts.join(" · ")
}

function formatWords(count) {
  return String(count).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
}

export function markLabel(mark) {
  if (mark.state === "rewrite") return `第 ${mark.n} 章，待返工`
  if (mark.state === "done") return `第 ${mark.n} 章，已完成`
  if (mark.state === "current") return `第 ${mark.n} 章，正在写`
  return `第 ${mark.n} 章，未写`
}
