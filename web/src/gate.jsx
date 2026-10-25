import { useState } from "react"

import { changePassword, currentUsername, login, register } from "./api.js"

const REMEMBER = "ainovel-account"

function rememberedName() {
  try {
    return localStorage.getItem(REMEMBER) || ""
  } catch {
    return ""
  }
}

function storeName(name, remember) {
  try {
    if (remember && name) localStorage.setItem(REMEMBER, name)
    else localStorage.removeItem(REMEMBER)
  } catch {
    // 浏览器不允许保存时，登录本身仍然完成。
  }
}

export function Login({ status, onEnter }) {
  const saved = rememberedName()
  const [mode, setMode] = useState("login")
  const [username, setUsername] = useState(saved)
  const [password, setPassword] = useState("")
  const [again, setAgain] = useState("")
  const [remember, setRemember] = useState(true)
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const registering = mode === "register"

  function switchMode(next) {
    setMode(next)
    setError("")
    setPassword("")
    setAgain("")
    setShowPassword(false)
  }

  async function submit(event) {
    event.preventDefault()
    setError("")
    if (!username.trim()) {
      setError("请填写用户名。")
      return
    }
    if (password.length < 8) {
      setError("密码至少 8 位。")
      return
    }
    if (registering && password !== again) {
      setError("两次密码不一致。")
      return
    }
    setBusy(true)
    try {
      const name = username.trim()
      if (registering) await register(name, password)
      else await login(name, password)
      storeName(name, remember)
      onEnter()
    } catch (reason) {
      setError(reason.message || "控制室没有应答。")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="door">
      <header className="door-bar">
        <span className="door-seal" aria-hidden="true">文</span>
        <span className="door-brand">ainovel</span>
        <span className="door-here">进门</span>
      </header>
      {status === "loading" ? (
        <p className="door-wait" role="status">正在确认登录</p>
      ) : (
        <div className="door-stage">
          <div className="door-hero">
            <h1>
              进门
              <span className="door-mark" aria-hidden="true">文</span>
            </h1>
            <p>
              <span>每一个故事的开始</span>
              <span>都从这里启程</span>
            </p>
          </div>
          <form className="door-card" onSubmit={submit}>
            <i className="door-corner tl" aria-hidden="true" />
            <i className="door-corner tr" aria-hidden="true" />
            <i className="door-corner bl" aria-hidden="true" />
            <i className="door-corner br" aria-hidden="true" />
            <Landscape />
            <div className="door-welcome">
              <span />
              <h2>{registering ? "欢迎登记" : "欢迎回来"}</h2>
              <span />
            </div>
            <p className="door-sub">
              {registering ? "登记后开始书写属于你的故事" : "登录后继续书写属于你的精彩故事"}
            </p>
            {status === "down" ? <p className="door-error" role="status">控制室没有应答。</p> : null}
            <label className="door-field">
              <UserIcon />
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="用户名 / 账号"
                aria-label="用户名"
                autoComplete="username"
                maxLength={40}
              />
            </label>
            <label className="door-field">
              <LockIcon />
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="密码"
                aria-label="密码"
                autoComplete={registering ? "new-password" : "current-password"}
              />
              <button
                type="button"
                className="door-eye"
                aria-label={showPassword ? "隐藏密码" : "显示密码"}
                onClick={() => setShowPassword((value) => !value)}
              >
                <EyeIcon off={showPassword} />
              </button>
            </label>
            {registering ? (
              <label className="door-field">
                <LockIcon />
                <input
                  type={showPassword ? "text" : "password"}
                  value={again}
                  onChange={(event) => setAgain(event.target.value)}
                  placeholder="确认密码"
                  aria-label="确认密码"
                  autoComplete="new-password"
                />
              </label>
            ) : null}
            {error ? <p className="door-error" role="status">{error}</p> : null}
            <button className="door-submit" type="submit" disabled={busy}>
              {busy ? "请稍候" : registering ? "登记 →" : "进入 →"}
            </button>
            <div className="door-foot">
              {registering ? <span /> : (
                <label className="door-check">
                  <input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} />
                  <span>记住账号</span>
                </label>
              )}
              {registering ? (
                <button type="button" className="door-switch" onClick={() => switchMode("login")}>已有账号，去登录 →</button>
              ) : (
                <button type="button" className="door-switch" onClick={() => switchMode("register")}>没有账号，去登记 →</button>
              )}
            </div>
          </form>
        </div>
      )}
    </div>
  )
}

function Landscape() {
  return (
    <svg className="door-landscape" viewBox="0 0 280 78" aria-hidden="true">
      <path d="M18 58c28-22 46-22 68-8 16 10 28 8 42-6 18-18 36-20 58-6 16 10 30 8 48-4 12-8 22-8 34 2" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M40 58c18-16 34-16 50-4 12 8 22 6 34-8 14-16 30-18 48-4" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.7" />
      <circle cx="196" cy="24" r="7" fill="none" stroke="currentColor" strokeWidth="1" />
      <path d="M24 64h232" stroke="currentColor" strokeWidth="0.8" opacity="0.45" />
      <path d="M78 66c16 4 28 4 44 0M150 67c18 5 34 4 52-1" fill="none" stroke="currentColor" strokeWidth="0.8" opacity="0.4" />
    </svg>
  )
}

function UserIcon() {
  return (
    <svg className="door-icon" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="8" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M5.5 19.2c1.4-3 3.6-4.4 6.5-4.4s5.1 1.4 6.5 4.4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

function LockIcon() {
  return (
    <svg className="door-icon" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="6" y="10.5" width="12" height="8.5" rx="1.6" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8.5 10.5V8.2a3.5 3.5 0 0 1 7 0v2.3" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  )
}

function EyeIcon({ off }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6z" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="12" cy="12" r="2.4" fill="none" stroke="currentColor" strokeWidth="1.6" />
      {off ? <path d="M5 19L19 5" stroke="currentColor" strokeWidth="1.6" /> : null}
    </svg>
  )
}

export function PasswordScreen() {
  const [username, setUsername] = useState(currentUsername)
  const [current, setCurrent] = useState("")
  const [password, setPassword] = useState("")
  const [again, setAgain] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  async function submit(event) {
    event.preventDefault()
    setError("")
    setNotice("")
    if (password !== again) {
      setError("两次密码不一致。")
      return
    }
    setBusy(true)
    try {
      const saved = await changePassword({
        username: username.trim(),
        current,
        password,
      })
      setUsername(saved.username || username.trim())
      setCurrent("")
      setPassword("")
      setAgain("")
      setNotice("密码已更换。其他已经打开的页面要重新进入。")
    } catch (reason) {
      setError(reason.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="page narrow">
      <p className="eyebrow"><a href="#/">书架</a></p>
      <h1>改密码</h1>
      <p className="lede">换过之后，这一页继续留着。别处已经登录的页面要重新进入。</p>
      <form className="model-form" onSubmit={submit}>
        <label>
          用户名
          <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required maxLength={40} />
        </label>
        <label>
          现在的密码
          <input type="password" value={current} onChange={(event) => setCurrent(event.target.value)} autoComplete="current-password" required />
        </label>
        <label>
          新密码
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" required minLength={8} />
        </label>
        <label>
          再输入一次
          <input type="password" value={again} onChange={(event) => setAgain(event.target.value)} autoComplete="new-password" required minLength={8} />
        </label>
        {error ? <p className="banner" role="status">{error}</p> : null}
        {notice ? <p className="banner ok" role="status">{notice}</p> : null}
        <button className="signal" type="submit" disabled={busy || !username.trim() || !current || password.length < 8 || again.length < 8}>保存</button>
      </form>
    </main>
  )
}
