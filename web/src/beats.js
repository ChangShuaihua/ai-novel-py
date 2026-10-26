export function parseOutline(text) {
  const items = []
  for (const raw of String(text || "").split(/\n+/)) {
    let line = raw.trim()
    if (!line) continue
    const numbered = line.match(/^\d+\.\s*(.*)$/)
    if (numbered) line = numbered[1]
    let title = line
    let summary = ""
    const full = line.indexOf("：")
    const ascii = line.indexOf(":")
    const at = full >= 0 && (ascii < 0 || full <= ascii) ? full : ascii
    if (at >= 0) {
      title = line.slice(0, at).trim()
      summary = line.slice(at + 1).trim()
    }
    title = title.trim()
    if (!title) continue
    items.push({ title, summary })
  }
  return items
}

export function formatOutline(items) {
  return items
    .map((item, index) => {
      const title = String(item.title || "").trim()
      const summary = String(item.summary || "").trim()
      if (!title && !summary) return ""
      const name = title || summary
      const rest = title && summary ? `：${summary}` : ""
      return `${index + 1}. ${name}${rest}`
    })
    .filter(Boolean)
    .join("\n")
}

export function parseParagraphs(text) {
  const parts = String(text || "").split(/\n+/).map((line) => line.trim()).filter(Boolean)
  return parts.length ? parts : [""]
}

export function joinParagraphs(parts) {
  return parts.map((part) => String(part || "").trim()).filter((part) => part).join("\n\n")
}

export function reorder(list, from, to) {
  if (from === to || from < 0 || to < 0 || from >= list.length || to >= list.length) return list.slice()
  const next = list.slice()
  const [item] = next.splice(from, 1)
  next.splice(to, 0, item)
  return next
}
