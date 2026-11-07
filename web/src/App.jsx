import { Component, useEffect, useState } from "react"

import { logout, restoreSession } from "./api.js"
import { Login, PasswordScreen } from "./gate.jsx"
import { DeskScreen, ImportScreen, Library, LibraryReader, ListingScreen, ModelScreen, NewBook, OutlineScreen, PremiseScreen, Reader, Shelf } from "./screens.jsx"

const SCREEN = {
  "/": "书架",
  "/model": "接入模型",
  "/new": "新书",
  "/premise": "前提",
  "/outline": "大纲",
  "/desk": "写作",
  "/read": "章节阅读",
  "/import": "导入确认",
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

export class AppBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error("页面渲染失败", error, info)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <main className="crash-page" role="alert">
        <div className="crash-card">
          <span className="seal" aria-hidden="true">文</span>
          <h1>页面没有正常打开</h1>
          <p>页面数据可能暂时不完整。重新加载通常可以恢复；如果仍然出现，请保留控制台错误。</p>
          <div className="page-actions">
            <button className="signal" type="button" onClick={() => window.location.reload()}>重新加载</button>
            <a className="quiet-link" href="#/" onClick={() => this.setState({ error: null })}>回到书架</a>
          </div>
        </div>
      </main>
    )
  }
}

function Studio({ onLeave }) {
  const route = useRoute()
  if (route.path === "/") return <Shelf onLeave={onLeave} />
  if (route.path === "/library") return <Library onLeave={onLeave} />
  if (route.path === "/library/read") return <LibraryReader directory={route.directory} onLeave={onLeave} />
  if (route.path === "/new") return <NewBook directory={route.directory} onLeave={onLeave} />
  if (route.path === "/premise") return <PremiseScreen directory={route.directory} onLeave={onLeave} />
  if (route.path === "/outline") return <OutlineScreen directory={route.directory} onLeave={onLeave} />
  if (route.path === "/desk") return <DeskScreen directory={route.directory} onLeave={onLeave} />
  if (route.path === "/model") return <ModelScreen onLeave={onLeave} />
  if (route.path === "/pass") return <PasswordScreen onLeave={onLeave} />
  const painted = route.path === "/read" || route.path === "/listing"
  return (
    <div className={painted ? "room painted" : "room"}>
      <Lintel here={SCREEN[route.path]}>
        <div className="appbar-actions">
          {route.path === "/model" ? null : <a className="appbar-model" href="#/model">接入模型</a>}
          <a className="appbar-model" href="#/pass">改密码</a>
          <button type="button" className="appbar-leave" onClick={onLeave}>离开</button>
        </div>
      </Lintel>
      {route.path === "/read" ? <Reader directory={route.directory} /> : null}
      {route.path === "/import" ? <ImportScreen directory={route.directory} /> : null}
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
  const known = ["/", "/library", "/library/read", "/model", "/new", "/premise", "/outline", "/desk", "/read", "/import", "/listing", "/pass"]
  return {
    path: known.includes(path) ? path : "/",
    directory: params.get("directory") || "",
  }
}
