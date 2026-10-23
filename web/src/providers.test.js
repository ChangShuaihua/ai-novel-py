import assert from "node:assert/strict"
import test from "node:test"

import {
  DEFAULT_MODEL,
  DEFAULT_PROVIDER,
  PROVIDERS,
  callName,
  modelForProvider,
  modelOptions,
  providerOptions,
} from "./providers.js"

test("每个提供方都有可选模型，名字不重复", () => {
  const providers = new Set()
  for (const provider of PROVIDERS) {
    assert.equal(providers.has(provider.id), false)
    providers.add(provider.id)
    assert.ok(provider.models.length > 0)
    const models = new Set()
    for (const model of provider.models) {
      assert.equal(models.has(model.id), false)
      assert.equal(model.id.includes("/"), false)
      models.add(model.id)
    }
  }
  assert.equal(PROVIDERS[0].id, DEFAULT_PROVIDER)
  assert.equal(PROVIDERS[0].models[0].id, DEFAULT_MODEL)
})

test("换提供方时，不属于它的模型换成该提供方的第一个", () => {
  assert.equal(modelForProvider("openai", "deepseek-chat"), "gpt-6.1-sol")
  assert.equal(modelForProvider("openai", "gpt-4.1"), "gpt-4.1")
  assert.equal(modelForProvider("custom", "kept-model"), "kept-model")
})

test("已保存但不在列表里的名字仍能选中", () => {
  const providers = providerOptions("custom-lab")
  assert.equal(providers[0].id, "custom-lab")
  assert.ok(providers.some((item) => item.id === "deepseek"))
  const models = modelOptions("openai", "private-model")
  assert.equal(models[0].id, "private-model")
  assert.ok(models.some((item) => item.id === "gpt-4.1"))
})

test("调用名由提供方和模型拼成", () => {
  assert.equal(callName("openai", "gpt-4.1"), "openai/gpt-4.1")
  assert.equal(callName("openai", "openai/gpt-4.1"), "openai/gpt-4.1")
  assert.equal(callName("", "gpt-4.1"), "")
})
