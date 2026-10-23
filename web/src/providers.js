/** 提供方前缀与 LiteLLM 的调用名一致。模型只列适合写作的对话模型。 */

export const PROVIDERS = [
  {
    id: "deepseek",
    label: "DeepSeek",
    models: [
      { id: "deepseek-v4-pro", label: "DeepSeek V4 Pro" },
      { id: "deepseek-chat", label: "DeepSeek Chat" },
      { id: "deepseek-flash", label: "DeepSeek Flash" },
      { id: "deepseek-reasoner", label: "DeepSeek Reasoner" },
    ],
  },
  {
    id: "dashscope",
    label: "通义千问",
    models: [
      { id: "qwen-max", label: "Qwen Max" },
      { id: "qwen-plus", label: "Qwen Plus" },
      { id: "qwen-turbo", label: "Qwen Turbo" },
      { id: "qwen3-235b-a22b", label: "Qwen3 235B" },
    ],
  },
  {
    id: "moonshot",
    label: "Kimi",
    models: [
      { id: "kimi-k2.5", label: "Kimi K2.5" },
      { id: "moonshot-v1-128k", label: "Moonshot 128K" },
      { id: "moonshot-v1-32k", label: "Moonshot 32K" },
      { id: "moonshot-v1-8k", label: "Moonshot 8K" },
    ],
  },
  {
    id: "zai",
    label: "智谱",
    models: [
      { id: "glm-4.7", label: "GLM-4.7" },
      { id: "glm-4.6", label: "GLM-4.6" },
      { id: "glm-4.5", label: "GLM-4.5" },
      { id: "glm-4.5-flash", label: "GLM-4.5 Flash" },
    ],
  },
  {
    id: "openai",
    label: "OpenAI",
    models: [
      { id: "gpt-6.1-sol", label: "GPT-6.1 Sol" },
      { id: "gpt-6-luna", label: "GPT-6 Luna" },
      { id: "gpt-5.5", label: "GPT-5.5" },
      { id: "gpt-4.1", label: "GPT-4.1" },
    ],
  },
  {
    id: "anthropic",
    label: "Anthropic",
    models: [
      { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5" },
      { id: "claude-opus-5-5", label: "Claude Opus 5.5" },
      { id: "claude-haiku-5-5", label: "Claude Haiku 5.5" },
      { id: "claude-fable-5-1", label: "Claude Fable 5.1" },
    ],
  },
  {
    id: "gemini",
    label: "Gemini",
    models: [
      { id: "gemini-3.8-flash", label: "Gemini 3.8 Flash" },
      { id: "gemini-flash-latest", label: "Gemini Flash" },
      { id: "gemini-2.0-flash", label: "Gemini 2.0 Flash" },
    ],
  },
]

export const DEFAULT_PROVIDER = PROVIDERS[0].id
export const DEFAULT_MODEL = PROVIDERS[0].models[0].id

const PROVIDER_NOTES = {
  moonshot: "国内账号把接口地址填成 https://api.moonshot.cn/v1。",
  dashscope: "国内一般留空。国际站填 https://dashscope-intl.aliyuncs.com/compatible-mode/v1。",
}

export function providerNote(provider) {
  return PROVIDER_NOTES[provider] || ""
}

export function providerOptions(current) {
  const options = PROVIDERS.map((item) => ({ id: item.id, label: item.label }))
  if (current && !options.some((item) => item.id === current)) {
    options.unshift({ id: current, label: current })
  }
  return options
}

export function modelOptions(provider, selected) {
  const known = PROVIDERS.find((item) => item.id === provider)
  const options = known ? known.models.map((item) => ({ id: item.id, label: item.label })) : []
  if (selected && !options.some((item) => item.id === selected)) {
    options.unshift({ id: selected, label: selected })
  }
  return options
}

export function modelForProvider(provider, current) {
  const known = PROVIDERS.find((item) => item.id === provider)
  if (known?.models.some((item) => item.id === current)) return current
  if (!known && current) return current
  return known?.models[0]?.id || ""
}

export function callName(provider, model) {
  if (!provider || !model) return ""
  if (model.includes("/")) return model
  return `${provider}/${model}`
}
