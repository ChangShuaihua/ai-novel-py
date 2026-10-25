import { useCallback, useEffect, useState } from "react"

let accessToken = ""
let currentName = ""
let refreshing = null

const API_BASE = String(import.meta.env.VITE_API_BASE || "http://127.0.0.1:8765").replace(/\/$/, "")

function api(path) {
  return `${API_BASE}${path}`
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
    refreshing = fetch(api("/api/refresh"), {
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
  let response = await fetch(api(url), { ...rest, credentials: "include", headers })
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
  })
}

export function useSnapshot(directory) {
  const [snapshot, setSnapshot] = useState(null)
  const [loadError, setLoadError] = useState("")

  const refresh = useCallback(async () => {
    if (!directory) return null
    const next = await getSnapshot(directory)
    setSnapshot(next)
    setLoadError("")
    return next
  }, [directory])

  useEffect(() => {
    if (!directory) return undefined
    let stop = false
    async function tick() {
      try {
        const next = await getSnapshot(directory)
        if (!stop) {
          setSnapshot(next)
          setLoadError("")
        }
      } catch (error) {
        if (!stop) setLoadError(error.message)
      }
    }
    tick()
    const id = window.setInterval(tick, 1000)
    return () => {
      stop = true
      window.clearInterval(id)
    }
  }, [directory])

  return { snapshot, loadError, setSnapshot, refresh }
}

export function bookHref(path, directory) {
  if (!directory) return `#${path}`
  return `#${path}?directory=${encodeURIComponent(directory)}`
}
