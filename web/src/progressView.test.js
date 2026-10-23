import assert from "node:assert/strict"
import test from "node:test"

import { markLabel, progressCaption, progressView } from "./progressView.js"

test("大纲阶段标出当前位置，章格都还没写", () => {
  const view = progressView({ phase: "outline", total_chapters: 12, completed_chapters: [], next_chapter: 1 })
  assert.deepEqual(view.phases.map((item) => item.state), ["done", "done", "current", "ahead", "ahead"])
  assert.equal(view.marks.length, 12)
  assert.equal(view.marks.every((mark) => mark.state === "wait"), true)
  assert.equal(progressCaption(view, ""), "已完成 0 / 共 12 章")
})

test("写作中标出下一章，返工盖过已完成", () => {
  const view = progressView({
    phase: "writing",
    flow: "reviewing",
    total_chapters: 4,
    completed_chapters: [1, 2],
    pending_rewrites: [2],
    next_chapter: 3,
    total_word_count: 3200,
  })
  assert.deepEqual(view.marks.map((mark) => mark.state), ["done", "rewrite", "current", "wait"])
  assert.equal(progressCaption(view, "审阅"), "已完成 2 / 共 4 章 · 3,200 字 · 审阅")
  assert.equal(markLabel(view.marks[1]), "第 2 章，待返工")
})

test("写过大纲的章节要照实说", () => {
  const done = Array.from({ length: 13 }, (_, index) => index + 1)
  const view = progressView({
    phase: "writing",
    total_chapters: 12,
    completed_chapters: done,
    next_chapter: 14,
    total_word_count: 25524,
  })
  assert.equal(view.written, 12)
  assert.deepEqual(view.beyond, [13])
  assert.equal(view.marks.every((mark) => mark.state === "done"), true)
  assert.equal(progressCaption(view, ""), "大纲 12 章已写完 · 又写到第 13 章 · 25,524 字")
})

test("章数很多时不再逐格展开", () => {
  const view = progressView({ phase: "writing", total_chapters: 40, completed_chapters: [1, 2, 3], next_chapter: 4 })
  assert.equal(view.marks, null)
  assert.equal(view.written, 3)
  assert.equal(view.ratio, 3 / 40)
})
