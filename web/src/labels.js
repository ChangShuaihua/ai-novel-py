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

const STEP = {
  book: "书名与简介",
  premise: "前提",
  characters: "人物",
  world_rules: "世界规则",
  layered_outline: "分层大纲",
  outline: "大纲",
  update_compass: "故事方向",
  append_volume: "追加一卷",
  complete_book: "完本",
  foundation_audit: "设定核对",
  expand_next_arc: "展开下一弧",
  resolve_outline_feedback: "处理大纲反馈",
  plan: "本章规划",
  draft: "本章草稿",
  edit: "本章修改",
  consistency_check: "一致性检查",
  commit: "提交本章",
  review: "审阅",
  arc_summary: "弧摘要",
  volume_summary: "卷摘要",
}

const SCOPE = {
  global: "全书",
  chapter: "这一章",
  arc: "这一弧",
  volume: "这一卷",
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

export function stepLabel(step) {
  return STEP[step] || step || ""
}

export function scopeLabel(scope) {
  return SCOPE[scope] || scope || ""
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

export function severityLabel(severity) {
  return { critical: "严重", error: "错误", warning: "提醒" }[severity] || severity || ""
}
