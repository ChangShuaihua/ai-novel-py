import assert from "node:assert/strict"
import test from "node:test"

import { exportFileName, scopeLabel, severityLabel, shortPath, stepLabel } from "./labels.js"

test("检查点步骤用中文", () => {
  assert.equal(stepLabel("book"), "书名与简介")
  assert.equal(stepLabel("layered_outline"), "分层大纲")
  assert.equal(stepLabel("update_compass"), "故事方向")
  assert.equal(stepLabel("custom_step"), "custom_step")
})

test("检查点范围用中文", () => {
  assert.equal(scopeLabel("global"), "全书")
  assert.equal(scopeLabel("chapter"), "这一章")
})

test("路径只留两级，读起来像位置", () => {
  assert.equal(shortPath("D:\\Users\\a\\小说\\新建文件夹"), "小说 / 新建文件夹")
  assert.equal(shortPath("Desktop\\小说"), "Desktop / 小说")
})

test("诊断级别用中文", () => {
  assert.equal(severityLabel("critical"), "严重")
  assert.equal(severityLabel("error"), "错误")
  assert.equal(severityLabel("warning"), "提醒")
  assert.equal(severityLabel("note"), "note")
})

test("导出文件名去掉路径字符并补上 txt", () => {
  assert.equal(exportFileName("雨/夜"), "雨夜.txt")
  assert.equal(exportFileName("已经是.txt"), "已经是.txt")
  assert.equal(exportFileName(""), "小说.txt")
})
