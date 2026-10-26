import assert from "node:assert/strict"
import test from "node:test"

import { blocks, deskState } from "./deskState.js"

function snap(overrides = {}) {
  return {
    config_ready: true,
    config_dir: "C:/Users/me/.ainovel",
    locked: false,
    lock_path: "",
    import_status: "",
    import_detail: "",
    phase: "writing",
    running: false,
    paused: false,
    pending_rewrites: [],
    advance_mode: "auto",
    advance_permit_chapter: 0,
    advance_hold: null,
    completed_chapters: [1],
    next_chapter: 2,
    ...overrides,
  }
}

test("配置缺失挡住后面的主操作", () => {
  const state = deskState(snap({ config_ready: false, locked: true, phase: "complete" }))
  assert.equal(state.id, "config")
  assert.equal(state.primary, null)
  assert.equal(blocks(state, "import_confirm"), true)
  assert.match(state.sentence, /还没接入模型/)
})

test("目录占用优先于导入确认", () => {
  const state = deskState(snap({ locked: true, lock_path: "D:/book/.ainovel.lock", import_status: "await_confirmation" }))
  assert.equal(state.id, "locked")
  assert.equal(state.primary, null)
  assert.equal(blocks(state, "steer"), true)
  assert.match(state.sentence, /ainovel\.lock/)
})

test("导入待确认的主操作是确认切分", () => {
  const state = deskState(snap({ import_status: "await_confirmation", phase: "complete" }))
  assert.equal(state.primary, "import_confirm")
  assert.equal(state.label, "确认切分")
  assert.equal(blocks(state, "next"), true)
})

test("导入进行中没有主按钮", () => {
  const state = deskState(snap({ import_status: "working", import_detail: "正在分析第 2 章", running: true }))
  assert.equal(state.primary, null)
  assert.match(state.sentence, /第 2 章/)
})

test("完本没有主按钮", () => {
  const state = deskState(snap({ phase: "complete", pending_rewrites: [1] }))
  assert.equal(state.id, "complete")
  assert.equal(state.primary, null)
  assert.equal(blocks(state, "next"), true)
})

test("返工挡住放行", () => {
  const state = deskState(snap({ pending_rewrites: [3, 1], advance_mode: "review", running: false }))
  assert.equal(state.primary, "resume")
  assert.equal(state.label, "继续")
  const running = deskState(snap({ pending_rewrites: [3], advance_mode: "review", running: true }))
  assert.equal(running.primary, "steer")
})

test("等待放行使用引擎已有的说法", () => {
  const ready = deskState(snap({ advance_mode: "review", completed_chapters: [], next_chapter: 1 }))
  assert.equal(ready.sentence, "规划已就绪，逐章验收等待放行第 1 章")
  assert.equal(ready.label, "放行下一章")
  const later = deskState(snap({ advance_mode: "review", completed_chapters: [2, 4], next_chapter: 5 }))
  assert.equal(later.sentence, "已完成至第 4 章，逐章验收等待放行第 5 章")
})

test("许可、暂停或返工时不能放行", () => {
  assert.notEqual(deskState(snap({ advance_mode: "review", advance_permit_chapter: 2 })).id, "permit")
  assert.equal(deskState(snap({ advance_mode: "review", paused: true, advance_hold: { after: "boundary", reason: "停" } })).id, "hold")
  assert.notEqual(deskState(snap({ advance_mode: "review", running: true })).primary, "next")
})

test("边界暂停优先于规划中的继续", () => {
  const state = deskState(snap({ phase: "outline", paused: true, advance_hold: { after: "boundary", reason: "停" }, running: false }))
  assert.equal(state.id, "hold")
  assert.equal(state.label, "继续")
})

test("规划中和自动写作", () => {
  assert.equal(deskState(snap({ phase: "premise", running: false })).label, "继续")
  assert.equal(deskState(snap({ phase: "init", running: true })).primary, "steer")
  assert.equal(deskState(snap({ phase: "writing", advance_mode: "auto", running: true })).id, "auto")
  assert.equal(deskState(snap({ phase: "writing", advance_mode: "review", running: true, advance_permit_chapter: 3 })).id, "writing")
})

test("停住之后主按钮是继续", () => {
  const state = deskState(snap({ phase: "writing", running: false, advance_mode: "auto" }))
  assert.equal(state.id, "idle")
  assert.equal(state.label, "继续")
  assert.equal(blocks(state, "next"), true)
})

test("没有进度时不提供继续", () => {
  const state = deskState(snap({ phase: "", completed_chapters: [] }))
  assert.equal(state.id, "empty")
  assert.equal(state.primary, null)
})

test("题目确认挡住自动推进", () => {
  const state = deskState(snap({ guide: { stage: "title", title: "雨夜", chapter: 0 } }))
  assert.equal(state.id, "guide")
  assert.equal(state.primary, null)
  assert.equal(blocks(state, "resume"), true)
  assert.match(state.sentence, /确认或改完/)
})
