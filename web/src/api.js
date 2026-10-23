import { useCallback, useEffect, useState } from "react"

async function request(url, options) {
  const response = await fetch(url, options)
  let data = {}
  try {
    data = await response.json()
  } catch {
    data = {}
  }
  if (!response.ok) {
    throw new Error(data.error || "请求没有完成")
  }
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
