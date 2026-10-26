const PHASE = {
  init: "起步",
  premise: "前提",
  outline: "大纲",
  writing: "写作",
  complete: "完本",
}

const FLOW = {
  writing: "写作",
  reviewing: "审阅",
  rewriting: "返工",
  polishing: "打磨",
  steering: "干预",
}

const HOLD = {
  boundary: "工作边界",
  rewrites_drained: "返工排空",
  chapter: "指定章",
}

export function phaseLabel(phase) {
  return PHASE[phase] || ""
}

export function flowLabel(flow) {
  return FLOW[flow] || ""
}

export function holdLabel(after) {
  return HOLD[after] || after || ""
}

export function exportFileName(title) {
  const cleaned = String(title || "").replace(/[\\/:*?"<>|\r\n]/g, "").trim().replace(/^\.+|\.+$/g, "")
  const base = cleaned || "小说"
  return base.toLowerCase().endsWith(".txt") ? base : `${base}.txt`
}

export function bookTitle(snapshot) {
  if (snapshot.title) return snapshot.title
  return folderName(snapshot.directory) || "未命名"
}

export function folderName(directory) {
  const parts = String(directory || "").split(/[\\/]/).filter(Boolean)
  return parts[parts.length - 1] || ""
}

export function shortPath(directory) {
  const parts = String(directory || "").split(/[\\/]/).filter(Boolean)
  if (parts.length <= 2) return parts.join(" / ")
  return parts.slice(-2).join(" / ")
}
