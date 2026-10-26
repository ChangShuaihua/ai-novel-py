const STOP = new Set([
  "我们", "你们", "他们", "她们", "自己", "什么", "这个", "那个", "一个", "这里", "那里",
  "父亲", "母亲", "爸爸", "妈妈", "今天", "现在", "然后", "已经", "没有", "不是",
  "因为", "所以", "如果", "但是", "可是", "而且", "知道", "时候", "地方", "开始",
  "出来", "起来", "下去", "上来", "进去", "出去", "回来", "过来", "过去", "一声",
  "手指", "膝盖", "目光", "眼睛", "声音", "脚步", "现场", "凭借", "听觉", "节奏", "线索",
])

const NAME = /(?:^|[，。！？、；\n]|在|跟|和|与|向|对|把|见)([一-龥]{2,3})(?=的|说|道|问|看|笑|听|坐|没|把|对|又|从|在|是)/g
const CALLED = /叫([一-龥]{2,3})(?=[，。！？、是的])/g

export function peopleFrom(text, { min = 2 } = {}) {
  const counts = new Map()
  const called = new Set()
  const source = String(text || "")
  for (const match of source.matchAll(NAME)) {
    const name = match[1]
    if (STOP.has(name) || /^[她他我你]/.test(name)) continue
    counts.set(name, (counts.get(name) || 0) + 1)
  }
  for (const match of source.matchAll(CALLED)) {
    const name = match[1]
    if (STOP.has(name)) continue
    called.add(name)
    counts.set(name, Math.max(counts.get(name) || 0, 1))
  }
  return [...counts.entries()]
    .filter(([name, count]) => called.has(name) || count >= min)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh"))
    .slice(0, 6)
    .map(([name]) => name)
}

export function relationsFrom(text, names) {
  const found = []
  for (const paragraph of String(text || "").split(/\n+/)) {
    const present = names.filter((name) => paragraph.includes(name))
    if (present.length < 2) continue
    const label = present.slice(0, 3).join("、")
    if (!found.includes(label)) found.push(label)
  }
  return found.slice(0, 4)
}

export function assistView({
  outline = [],
  chapter = 0,
  body = "",
  synopsis = "",
  stage = "",
  completed = [],
  instruction = "",
} = {}) {
  const doneNumbers = new Set(completed.map(Number))
  const items = outline.map((item) => {
    const n = Number(item.chapter) || 0
    const state = n === Number(chapter) ? "current" : doneNumbers.has(n) ? "done" : "wait"
    return { n, title: String(item.title || ""), summary: String(item.summary || ""), state }
  })
  const written = items.filter((item) => doneNumbers.has(item.n)).length
  const source = body.trim() || [synopsis, ...items.map((item) => `${item.title} ${item.summary}`)].join("\n")
  const people = peopleFrom(source)
  const relations = body.trim() ? relationsFrom(body, people) : []
  const plants = plantsFrom(items, chapter, body, people)
  const notes = notesFrom({ items, chapter, body, stage, people, instruction })
  return {
    written,
    total: items.length,
    items,
    people,
    relations,
    plants,
    notes,
  }
}

function plantsFrom(items, chapter, body, people) {
  const later = items.filter((item) => item.n > Number(chapter || 0))
  const plants = []
  for (const item of later) {
    const blob = `${item.title}${item.summary}`
    const hit = people.filter((name) => blob.includes(name) && body.includes(name))
    if (!hit.length) continue
    plants.push({ chapter: item.n, title: item.title, note: item.summary || `${hit.join("、")}会在第 ${item.n} 章继续` })
  }
  const next = later[0]
  if (next && !plants.some((item) => item.chapter === next.n)) {
    plants.unshift({
      chapter: next.n,
      title: next.title,
      note: next.summary || "下一章从这里接",
    })
  }
  return plants.slice(0, 4)
}

function notesFrom({ items, chapter, body, stage, people = [], instruction }) {
  const notes = []
  if (instruction) notes.push(instruction)
  const plan = items.find((item) => item.n === Number(chapter))
  if (plan && body.trim()) {
    const expected = peopleFrom(plan.summary, { min: 1 })
    const missing = expected.filter((name) => !body.includes(name))
    const castInPlan = people.filter((name) => `${plan.title}${plan.summary}`.includes(name))
    if (missing.length) notes.push(`大纲里这一章要写到${missing.join("、")}，正文里还没有。`)
    else if (expected.length || castInPlan.length) notes.push("这一章的人和大纲对得上。")
    else if (plan.summary) notes.push(`这一章大纲要写的是：${plan.summary.length > 48 ? `${plan.summary.slice(0, 48)}…` : plan.summary}`)
  } else if (stage === "outline" && items.length) {
    notes.push(`大纲共 ${items.length} 章。确认后从第 1 章写起。`)
  } else if (stage === "title") {
    notes.push("题目定下来之后再排大纲。")
  } else if (stage === "chapter") {
    notes.push("这一章还没有正文。")
  } else if (!items.length) {
    notes.push("还没有大纲。")
  }
  return notes.slice(0, 3)
}
