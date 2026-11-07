import { useCallback, useEffect, useRef, useState } from "react"

let accessToken = ""
let currentName = ""
let refreshing = null

const API_BASE = String(import.meta.env.VITE_API_BASE || "http://127.0.0.1:8765").replace(/\/$/, "")
const REQUEST_TIMEOUT = 15000

function api(path) {
  return `${API_BASE}${path}`
}

async function timedFetch(url, options = {}) {
  const timeout = options.timeout ?? REQUEST_TIMEOUT
  const { timeout: _timeout, ...rest } = options
  const controller = new AbortController()
  const external = rest.signal
  const abort = () => controller.abort(external?.reason)
  if (external) {
    if (external.aborted) abort()
    else external.addEventListener("abort", abort, { once: true })
  }
  const timer = window.setTimeout(() => controller.abort(new Error("请求超时")), timeout)
  try {
    return await fetch(url, { ...rest, signal: controller.signal })
  } catch (error) {
    if (controller.signal.aborted && !external?.aborted) throw new Error("控制室响应超时，请稍后重试")
    throw error
  } finally {
    window.clearTimeout(timer)
    external?.removeEventListener("abort", abort)
  }
}

export function currentUsername() {
  return currentName
}

function remember(data) {
  accessToken = data.access_token || ""
  currentName = data.username || ""
}

function forget() {
  accessToken = ""
  currentName = ""
}

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return {}
  }
}

export function refreshAccess() {
  if (!refreshing) {
    refreshing = timedFetch(api("/api/refresh"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    })
      .then(async (response) => {
        const data = await readJson(response)
        if (!response.ok || !data.access_token) {
          forget()
          return false
        }
        remember(data)
        return true
      })
      .finally(() => {
        refreshing = null
      })
  }
  return refreshing
}

async function request(url, options = {}, allowRefresh = true) {
  const { quietAuth, ...rest } = options
  const headers = { ...(rest.headers || {}) }
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  let response
  try {
    response = await timedFetch(api(url), { ...rest, credentials: "include", headers })
  } catch (error) {
    throw new Error(error?.message || "控制室没有应答")
  }
  if (response.status === 401 && allowRefresh && !quietAuth) {
    const renewed = await refreshAccess()
    if (renewed) return request(url, options, false)
  }
  const data = await readJson(response)
  if (response.status === 401 && !quietAuth) {
    forget()
    window.dispatchEvent(new CustomEvent("ainovel-unauthenticated"))
  }
  if (!response.ok) {
    throw new Error(data.error || "请求没有完成")
  }
  return data
}

export async function restoreSession() {
  const ok = await refreshAccess()
  return { authenticated: ok, username: currentName }
}

export async function login(username, password) {
  const data = await request("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
    quietAuth: true,
  })
  remember(data)
  return data
}

export async function register(username, password) {
  const data = await request("/api/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
    quietAuth: true,
  })
  remember(data)
  return data
}

export async function logout() {
  try {
    await request("/api/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
      quietAuth: true,
    }, false)
  } finally {
    forget()
  }
}

export async function changePassword(payload) {
  const data = await request("/api/password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  remember(data)
  return data
}

export function getLibrary() {
  return request("/api/library")
}

export function getPublicLibrary() {
  return request("/api/public-library")
}

export function getPublicBook(directory) {
  const query = new URLSearchParams({ directory })
  return request(`/api/public-book?${query}`)
}

export function publishBook(directory, visible = true) {
  return request("/api/public-library", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ directory, action: visible ? "publish" : "unpublish" }),
  })
}

export function addComment(directory, body) {
  return request("/api/comments", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ directory, body }),
  })
}

export function pickDirectory() {
  return request("/api/directory", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  })
}

export function pickSaveFile(name) {
  return request("/api/save-file", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name || "" }),
  })
}

export function attachBook(directory) {
  return request("/api/library", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ directory }),
  })
}

export function moveBook(directory, action) {
  return request("/api/library", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ directory, action }),
  })
}

export function emptyTrash() {
  return request("/api/library", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "empty" }),
  })
}

export function getSnapshot(directory) {
  const query = new URLSearchParams({ directory })
  return request(`/api/snapshot?${query}`)
}

export function getModel() {
  return request("/api/model")
}

export function saveModel(payload) {
  return request("/api/model", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
}

export function composeSynopsis(payload) {
  return request("/api/synopsis", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    timeout: 120000,
  })
}

export function checkModel(payload) {
  return request("/api/model/check", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
}

export function sendIntent(payload) {
  return request("/api/intent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    timeout: 120000,
  })
}

export function useLiveText(target, enabled) {
  const [text, setText] = useState("")
  const key = typeof target === "string" ? target : ""
  useEffect(() => {
    if (!enabled || !key) {
      setText("")
      return undefined
    }
    const controller = new AbortController()
    const query = new URLSearchParams(key.startsWith("channel:") ? { channel: key.slice(8) } : { directory: key })
    const headers = { Accept: "text/event-stream" }
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    fetch(api(`/api/live?${query}`), { headers, credentials: "include", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok || !response.body) return
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let pending = ""
        while (true) {
          const step = await reader.read()
          if (step.done) return
          pending += decoder.decode(step.value, { stream: true })
          let cut = pending.indexOf("\n\n")
          while (cut >= 0) {
            const frame = pending.slice(0, cut)
            pending = pending.slice(cut + 2)
            const data = frame
              .split("\n")
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trim())
              .join("\n")
            if (data) {
              try {
                const event = JSON.parse(data)
                if (event.reset) setText(event.text || "")
                else if (event.text) setText((prev) => prev + event.text)
              } catch {
                // 半包或心跳以外的残帧先丢掉，下一帧还会接上。
              }
            }
            cut = pending.indexOf("\n\n")
          }
        }
      })
      .catch(() => {})
    return () => controller.abort()
  }, [key, enabled])
  return text
}

export function useSnapshot(directory) {
  const [snapshot, setSnapshot] = useState(null)
  const [loadError, setLoadError] = useState("")
  const serial = useRef(0)
  const packed = useRef("")

  const apply = useCallback((next) => {
    serial.current += 1
    packed.current = JSON.stringify(next)
    setSnapshot(next)
    setLoadError("")
  }, [])

  const refresh = useCallback(async () => {
    if (!directory) return null
    const next = await getSnapshot(directory)
    apply(next)
    return next
  }, [directory, apply])

  useEffect(() => {
    if (!directory) return undefined
    let stop = false
    let timer = 0
    async function tick() {
      const mine = serial.current
      let wait = 4000
      try {
        const next = await getSnapshot(directory)
        if (stop || mine !== serial.current) {
          wait = 1000
          return
        }
        wait = next.running ? 1000 : 4000
        const body = JSON.stringify(next)
        if (body !== packed.current) {
          packed.current = body
          setSnapshot(next)
          setLoadError("")
        }
      } catch (error) {
        if (!stop && mine === serial.current) setLoadError(error.message)
      } finally {
        if (!stop) timer = window.setTimeout(tick, wait)
      }
    }
    tick()
    return () => {
      stop = true
      window.clearTimeout(timer)
    }
  }, [directory])

  return { snapshot, loadError, setSnapshot: apply, refresh }
}

export function bookHref(path, directory) {
  if (!directory) return `#${path}`
  return `#${path}?directory=${encodeURIComponent(directory)}`
}
