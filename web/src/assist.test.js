import assert from "node:assert/strict"
import test from "node:test"

import { assistView, peopleFrom } from "./assist.js"

const body = [
  "凌晨四点十七分，林砚听见雨声停了。",
  "她坐在陆沉的车后座。陆沉从后视镜里看了她一眼。林砚没应声。",
  "第三名失踪者叫许薇，十九岁。",
  "雨点打在车顶上，一盏一盏路灯往后退。林砚看着窗外，陆沉没有再说话。这条路她来过，却一次都没有在夜里走到头。车里很安静，只有雨和发动机。她把没问完的话咽了回去，等红灯，等下一个路口，等陆沉终于把车停在旧楼门口。",
].join("\n")

test("people come from the written chapter", () => {
  const names = peopleFrom(body)
  assert.ok(names.includes("林砚"))
  assert.ok(names.includes("陆沉"))
  assert.ok(names.includes("许薇"))
  assert.equal(names.includes("出来"), false)
})

test("assistant reads the outline against this chapter", () => {
  const view = assistView({
    stage: "chapter",
    chapter: 1,
    body,
    completed: [1],
    outline: [
      { chapter: 1, title: "城市雨夜", summary: "林砚坐上陆沉的车，听见许薇的名字。" },
      { chapter: 2, title: "旧楼", summary: "林砚跟着地址找到许薇消失的地方。" },
    ],
  })
  assert.equal(view.written, 1)
  assert.equal(view.total, 2)
  assert.equal(view.items[0].state, "current")
  assert.ok(view.relations.some((item) => item.includes("林砚") && item.includes("陆沉")))
  assert.ok(view.plants.some((item) => item.chapter === 2 && item.note.includes("林砚")))
  assert.ok(view.notes.some((item) => item.includes("对得上")))
})
