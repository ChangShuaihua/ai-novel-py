import { useEffect, useState } from "react"

import { DeskScreen, DiagScreen, ImportScreen, ListingScreen, ModelScreen, NewBook, Reader, Shelf } from "./screens.jsx"

const SCREEN = {
  "/": "书架",
  "/model": "接入模型",
  "/new": "新书",
  "/desk": "写作现场",
  "/read": "章节阅读",
  "/import": "导入确认",
  "/diag": "诊断与导出",
  "/listing": "投稿资料",
}

export function App() {
  const route = useRoute()
  return (
    <div className="room">
      <header className="appbar">
        <a className="mark" href="#/">
          <span className="seal" aria-hidden="true">案</span>
          <span className="mark-name">ainovel</span>
        </a>
        <span className="appbar-here">{SCREEN[route.path]}</span>
        {route.path === "/model" ? null : <a className="appbar-model" href="#/model">接入模型</a>}
      </header>
      {route.path === "/model" ? <ModelScreen /> : null}
      {route.path === "/new" ? <NewBook directory={route.directory} /> : null}
      {route.path === "/desk" ? <DeskScreen directory={route.directory} /> : null}
      {route.path === "/read" ? <Reader directory={route.directory} /> : null}
      {route.path === "/import" ? <ImportScreen directory={route.directory} /> : null}
      {route.path === "/diag" ? <DiagScreen directory={route.directory} /> : null}
      {route.path === "/listing" ? <ListingScreen directory={route.directory} /> : null}
      {route.path === "/" ? <Shelf /> : null}
    </div>
  )
}

function useRoute() {
  const [route, setRoute] = useState(readRoute)
  useEffect(() => {
    const onChange = () => setRoute(readRoute())
    window.addEventListener("hashchange", onChange)
    return () => window.removeEventListener("hashchange", onChange)
  }, [])
  return route
}

function readRoute() {
  const raw = window.location.hash.replace(/^#/, "") || "/"
  const [path, query = ""] = raw.split("?")
  const params = new URLSearchParams(query)
  const known = ["/", "/model", "/new", "/desk", "/read", "/import", "/diag", "/listing"]
  return {
    path: known.includes(path) ? path : "/",
    directory: params.get("directory") || "",
  }
}
