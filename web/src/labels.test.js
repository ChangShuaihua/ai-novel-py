import assert from "node:assert/strict"
import test from "node:test"

import { exportFileName, shortPath } from "./labels.js"

test("路径只留两级，读起来像位置", () => {
  assert.equal(shortPath("D:\\Users\\a\\小说\\新建文件夹"), "小说 / 新建文件夹")
  assert.equal(shortPath("Desktop\\小说"), "Desktop / 小说")
})

test("导出文件名去掉路径字符并补上 txt", () => {
  assert.equal(exportFileName("雨/夜"), "雨夜.txt")
  assert.equal(exportFileName("已经是.txt"), "已经是.txt")
  assert.equal(exportFileName(""), "小说.txt")
})
