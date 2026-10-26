import assert from "node:assert/strict"
import test from "node:test"

import { formatOutline, joinParagraphs, parseOutline, parseParagraphs, reorder } from "./beats.js"

test("outline items keep their title and summary", () => {
  const items = parseOutline("1. 城市雨夜：林砚在雨里上车\n2. 名单：许薇是第三个失踪的人")
  assert.deepEqual(items, [
    { title: "城市雨夜", summary: "林砚在雨里上车" },
    { title: "名单", summary: "许薇是第三个失踪的人" },
  ])
  assert.equal(formatOutline(items), "1. 城市雨夜：林砚在雨里上车\n2. 名单：许薇是第三个失踪的人")
})

test("reordering renumbers from the new order", () => {
  const moved = reorder(parseOutline("1. 甲：一\n2. 乙：二\n3. 丙：三"), 2, 0)
  assert.equal(formatOutline(moved), "1. 丙：三\n2. 甲：一\n3. 乙：二")
})

test("chapter paragraphs split and join on blank lines", () => {
  assert.deepEqual(parseParagraphs("第一段。\n\n第二段。"), ["第一段。", "第二段。"])
  assert.equal(joinParagraphs(["第一段。", "", "第二段。"]), "第一段。\n\n第二段。")
})
