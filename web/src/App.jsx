import { useEffect, useState } from "react"

import { logout, restoreSession } from "./api.js"
import { Login, PasswordScreen } from "./gate.jsx"
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
  "/pass": "改密码",
}

export function App() {
  const session = useSession()
  if (session.status !== "in") {
    return <Login status={session.status} onEnter={session.enter} />
  }
  return <Studio onLeave={session.leave} />
}

function Studio({ onLeave }) {
  const route = useRoute()
  if (route.path === "/") return <Shelf onLeave={onLeave} />
  return (
    <div className="room">
      <Lintel here={SCREEN[route.path]}>
        <div className="appbar-actions">
          {route.path === "/model" ? null : <a className="appbar-model" href="#/model">接入模型</a>}
          {route.path === "/pass" ? null : <a className="appbar-model" href="#/pass">改密码</a>}
          <button type="button" className="appbar-leave" onClick={onLeave}>离开</button>
        </div>
      </Lintel>
      {route.path === "/model" ? <ModelScreen /> : null}
      {route.path === "/pass" ? <PasswordScreen /> : null}
      {route.path === "/new" ? <NewBook directory={route.directory} /> : null}
      {route.path === "/desk" ? <DeskScreen directory={route.directory} /> : null}
      {route.path === "/read" ? <Reader directory={route.directory} /> : null}
      {route.path === "/import" ? <ImportScreen directory={route.directory} /> : null}
      {route.path === "/diag" ? <DiagScreen directory={route.directory} /> : null}
      {route.path === "/listing" ? <ListingScreen directory={route.directory} /> : null}
    </div>
  )
}

function Lintel({ here, children }) {
  return (
    <header className="appbar">
      <a className="mark" href="#/">
        <span className="seal" aria-hidden="true">案</span>
        <span className="mark-name">ainovel</span>
      </a>
      <span className="appbar-here">{here}</span>
      {children}
    </header>
  )
}

function useSession() {
  const [status, setStatus] = useState("loading")

  useEffect(() => {
    let stop = false
    restoreSession()
      .then((data) => {
        if (!stop) setStatus(data.authenticated ? "in" : "out")
      })
      .catch(() => {
        if (!stop) setStatus("down")
      })
    const onOut = () => setStatus("out")
    window.addEventListener("ainovel-unauthenticated", onOut)
    return () => {
      stop = true
      window.removeEventListener("ainovel-unauthenticated", onOut)
    }
  }, [])

  return {
    status,
    enter() {
      setStatus("in")
    },
    async leave() {
      try {
        await logout()
      } catch {
        // 会话已经失效时，页面仍然回到进门。
      }
      setStatus("out")
    },
  }
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
  const known = ["/", "/model", "/new", "/desk", "/read", "/import", "/diag", "/listing", "/pass"]
  return {
    path: known.includes(path) ? path : "/",
    directory: params.get("directory") || "",
  }
}
