import { useState } from "react"

import { changePassword, currentUsername, login, register } from "./api.js"
import { StudioFrame } from "./screens.jsx"

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

  const title = registering ? "欢迎注册" : "欢迎回来"
  const action = busy ? "请稍候" : registering ? "注册" : "进入"

  return (
    <div className="door">
      {status === "loading" ? (
        <p className="door-wait" role="status">正在确认登录</p>
      ) : (
        <div className="door-stage">
          <form className="door-card" onSubmit={submit}>
            <div className="door-crest">
              <Landscape />
              <h1 className="door-title">
                {title}
                <span className="door-stamp" aria-hidden="true"><b>雅</b><b>藏</b></span>
              </h1>
            </div>
            <p className="door-sub">
              <i />
              {registering ? "注册后开始书写属于你的故事" : "登录后继续书写属于你的精彩故事"}
              <i />
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
                <button type="button" className="door-switch" onClick={() => switchMode("register")}>没有账号，去注册 →</button>
              )}
            </div>
            <button className="door-submit" type="submit" disabled={busy}>
              <span className="door-cloud left" aria-hidden="true"><AuspiciousCloud /></span>
              <span className="door-cloud right" aria-hidden="true"><AuspiciousCloud /></span>
              <span className="door-go">
                {action}
                {busy ? null : <i aria-hidden="true">→</i>}
              </span>
            </button>
            <p className="door-motto">
              <BookIcon />
              畅游二次元，开启你的创作之旅
            </p>
            <Corner className="tl" />
            <Corner className="tr" />
            <Corner className="bl" />
            <Corner className="br" />
          </form>
        </div>
      )}
    </div>
  )
}

function Landscape() {
  return (
    <svg className="door-landscape" viewBox="0 0 460 168" aria-hidden="true">
      <path d="M108 64C156 18 312 14 368 62" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" opacity="0.55" />
      <path d="M24 132c38-34 74-40 108-14 24-28 58-40 96-12 32-26 74-18 112 14 20-12 40-8 58 6" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M70 140c28-22 52-22 76-6 16 12 30 8 44-10 18-20 40-22 64-6 16 10 32 8 50-4" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity="0.65" />
      <path d="M330 48c7-4 12-4 18 1M354 40c6-4 11-3 16 1M374 52c5-3 9-3 13 1" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  )
}

function Corner({ className }) {
  return (
    <svg className={`door-corner ${className}`} viewBox="0 0 64 64" aria-hidden="true">
      <path d="M18 46V28c0-6 5-10 11-10h17" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
      <path d="M26 46V33c0-4 3-7 7-7h13" fill="none" stroke="currentColor" strokeWidth="0.9" strokeLinecap="round" />
      <circle cx="16" cy="18" r="6.2" fill="rgba(248,244,236,0.96)" stroke="currentColor" strokeWidth="1.15" />
      <circle cx="25" cy="14" r="4.4" fill="rgba(248,244,236,0.96)" stroke="currentColor" strokeWidth="1.05" />
      <circle cx="14" cy="27" r="4.2" fill="rgba(248,244,236,0.96)" stroke="currentColor" strokeWidth="1.05" />
    </svg>
  )
}

function AuspiciousCloud() {
  return (
    <svg viewBox="0 0 156 64" aria-hidden="true">
      <path d="M16 38c8-14 22-14 28-2 6-14 24-14 30 0 8-12 24-8 26 4 10-8 22 2 16 10" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" />
      <path d="M28 42c10 7 22 5 32-2 8 6 18 4 26-1" fill="none" stroke="currentColor" strokeWidth="1.15" strokeLinecap="round" />
    </svg>
  )
}

function BookIcon() {
  return (
    <svg className="door-book" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 6.4C10.3 5.3 8.4 4.8 6.2 4.8H4.2v13.1h2.2c1.9 0 3.5.4 5.6 1.6 2.1-1.2 3.7-1.6 5.6-1.6h2.2V4.8h-2c-2.2 0-4.1.5-5.8 1.6z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M12 6.4v13.1" fill="none" stroke="currentColor" strokeWidth="1.3" />
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

export function PasswordScreen({ onLeave }) {
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
    <StudioFrame here="改密码" title="改密码" seal="密" lede="换过之后，这一页继续留着。别处已经登录的页面要重新进入。" active="" onLeave={onLeave}>
      <form className="manuscript pass-form" onSubmit={submit}>
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
    </StudioFrame>
  )
}
