import { useEffect, useRef, useState } from "react"

import { attachBook, bookHref, checkModel, currentUsername, emptyTrash, getLibrary, getModel, moveBook, pickDirectory, pickSaveFile, saveModel, sendIntent, useSnapshot } from "./api.js"
import { blocks, deskState } from "./deskState.js"
import {
  DEFAULT_MODEL,
  DEFAULT_PROVIDER,
  callName,
  modelForProvider,
  modelOptions,
  providerNote,
  providerOptions,
} from "./providers.js"
import { bookTitle, exportFileName, flowLabel, folderName, holdLabel, phaseLabel, scopeLabel, severityLabel, shortPath, stepLabel } from "./labels.js"
import { markLabel, progressCaption, progressView } from "./progressView.js"

const STARRED = "ainovel-stars"
const SHELF_VIEWS = [
  ["all", "我的书架"],
  ["recent", "最近阅读"],
  ["done", "已完结"],
  ["stars", "收藏"],
]

function readStars() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STARRED) || "[]")
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function Shelf({ onLeave }) {
  const [library, setLibrary] = useState(null)
  const [picking, setPicking] = useState(false)
  const [loadError, setLoadError] = useState("")
  const [actionError, setActionError] = useState("")
  const [view, setView] = useState("all")
  const [query, setQuery] = useState("")
  const [searching, setSearching] = useState(false)
  const [stars, setStars] = useState(readStars)
  const [accountOpen, setAccountOpen] = useState(false)
  const [menuDir, setMenuDir] = useState(null)

  useEffect(() => {
    if (!accountOpen) return undefined
    function close() { setAccountOpen(false) }
    window.addEventListener("pointerdown", close)
    return () => window.removeEventListener("pointerdown", close)
  }, [accountOpen])

  useEffect(() => {
    let stop = false
    async function tick() {
      try {
        const next = await getLibrary()
        if (!stop) {
          setLibrary(next)
          setLoadError("")
        }
      } catch (reason) {
        if (!stop) setLoadError(reason.message)
      }
    }
    tick()
    const id = window.setInterval(tick, 2000)
    return () => {
      stop = true
      window.clearInterval(id)
    }
  }, [])

  async function chooseDirectory() {
    setPicking(true)
    setActionError("")
    try {
      const picked = await pickDirectory()
      if (picked.cancelled || !picked.directory) return
      const row = await attachBook(picked.directory)
      window.location.hash = row.has_progress ? bookHref("/desk", row.directory) : bookHref("/new", row.directory)
    } catch (reason) {
      setActionError(reason.message)
    } finally {
      setPicking(false)
    }
  }

  const books = library?.books || []
  const trash = library?.trash || []
  const needle = query.trim()
  const shown = books.filter((book) => {
    const title = book.title || folderName(book.directory)
    if (needle && !title.includes(needle)) return false
    if (view === "recent") return Boolean(book.has_progress)
    if (view === "done") return book.phase === "complete"
    if (view === "stars") return stars.includes(book.directory)
    return true
  })
  const cloths = clothsFor(shown)

  function toggleStar(directory) {
    setStars((current) => {
      const next = current.includes(directory)
        ? current.filter((item) => item !== directory)
        : [...current, directory]
      try { localStorage.setItem(STARRED, JSON.stringify(next)) } catch { /* 记不住时，这一页仍可看 */ }
      return next
    })
  }

  useEffect(() => {
    if (!menuDir) return undefined
    function onPointer(event) {
      const node = event.target.closest?.("[data-book]")
      if (node && node.getAttribute("data-book") === menuDir) return
      setMenuDir(null)
    }
    function onKey(event) {
      if (event.key === "Escape") setMenuDir(null)
    }
    window.addEventListener("pointerdown", onPointer)
    window.addEventListener("keydown", onKey)
    return () => {
      window.removeEventListener("pointerdown", onPointer)
      window.removeEventListener("keydown", onKey)
    }
  }, [menuDir])

  async function discardBook(directory) {
    setMenuDir(null)
    setActionError("")
    try {
      setLibrary(await moveBook(directory, "discard"))
    } catch (reason) {
      setActionError(reason.message)
    }
  }

  async function restoreBook(directory) {
    setActionError("")
    try {
      setLibrary(await moveBook(directory, "restore"))
    } catch (reason) {
      setActionError(reason.message)
    }
  }

  async function clearTrash() {
    setActionError("")
    try {
      setLibrary(await emptyTrash())
    } catch (reason) {
      setActionError(reason.message)
    }
  }
  const emptyCopy = books.length === 0
    ? ["暂无书籍", "去创作一本属于你的故事吧"]
    : view === "recent"
      ? ["还没有写过的书", "点进一本，写起来才算读过"]
      : view === "done"
        ? ["还没有完本", "写完的书会出现在这里"]
        : view === "stars"
          ? ["还没有收藏", "点书上的按钮，选择收藏"]
          : ["没有符合的书", "换一个字，或回到我的书架"]

  return (
    <div className="hall">
      <header className="hall-bar">
        <a className="mark" href="#/">
          <span className="seal" aria-hidden="true">文</span>
          <span className="mark-name">ainovel</span>
        </a>
        <span className="hall-here">书架</span>
        <div className="hall-tools">
          {searching ? (
            <input
              className="hall-search"
              value={query}
              placeholder="书名"
              aria-label="搜索书名"
              autoFocus
              onChange={(event) => setQuery(event.target.value)}
              onPointerDown={(event) => event.stopPropagation()}
            />
          ) : (
            <button type="button" className="hall-tool" onClick={() => setSearching(true)}>
              <SearchIcon /> 搜索
            </button>
          )}
          <button type="button" className="hall-tool" onClick={() => { setView("all"); setQuery(""); setSearching(false) }}>
            <WorksIcon /> 我的作品
          </button>
          <div className="hall-account" onPointerDown={(event) => event.stopPropagation()}>
            <button type="button" className="hall-tool" aria-expanded={accountOpen} onClick={() => setAccountOpen((open) => !open)}>
              <PersonIcon /> {currentUsername() || "登录"}
            </button>
            {accountOpen ? (
              <div className="hall-pop">
                <a href="#/model">接入模型</a>
                <a href="#/pass">改密码</a>
                <button type="button" onClick={onLeave}>离开</button>
              </div>
            ) : null}
          </div>
        </div>
      </header>
      <div className="hall-stage">
        <header className="hall-title">
          <h1>书架<span className="hall-seal" aria-hidden="true">架</span></h1>
          <p>每本书只回答现在写到哪。点进去，再决定下一步谁动。</p>
        </header>
        {library && !library.config_ready ? (
          <p className="banner" role="status">
            还没接入模型。需要模型的动作先停在这里。 <a href="#/model">接入模型</a>
          </p>
        ) : library?.model_label ? (
          <p className="model-line">当前模型 {library.model_label} · <a href="#/model">更换</a></p>
        ) : null}
        {actionError || loadError ? <p className="banner" role="status">{actionError || loadError}</p> : null}
        <div className="hall-body">
          <nav className="hall-menu" aria-label="书架分类">
            {SHELF_VIEWS.map(([id, label]) => (
              <button key={id} type="button" aria-current={view === id ? "true" : undefined} onClick={() => setView(id)}>
                <ViewIcon id={id} /> {label}
              </button>
            ))}
            <Wastebasket
              trash={trash}
              onRestore={restoreBook}
              onEmpty={clearTrash}
            />
          </nav>
          <section className="hall-case" aria-label="书架">
            <i className="hall-corner tl" aria-hidden="true" />
            <i className="hall-corner tr" aria-hidden="true" />
            <i className="hall-corner bl" aria-hidden="true" />
            <i className="hall-corner br" aria-hidden="true" />
            <div className="hall-bay">
              {shown.length === 0 ? (
                <div className="hall-empty">
                  <EmptyBooks />
                  <p>{emptyCopy[0]}</p>
                  <p className="hall-empty-sub">{emptyCopy[1]}</p>
                </div>
              ) : (
                <ul className="bookcase">
                  {shown.map((book, index) => {
                    const href = book.has_progress ? bookHref("/desk", book.directory) : bookHref("/new", book.directory)
                    const title = book.title || folderName(book.directory)
                    const known = book.total_chapters > 0
                    const pct = known ? Math.min(100, Math.round((100 * book.completed_count) / book.total_chapters)) : 0
                    const count = known ? `${book.completed_count}/${book.total_chapters}` : String(book.completed_count)
                    const starred = stars.includes(book.directory)
                    return (
                      <li key={book.directory} className="hall-book" data-book={book.directory}>
                        <a
                          className={book.locked ? "volume held" : "volume"}
                          data-cloth={cloths[index]}
                          href={href}
                          title={book.directory}
                          style={{ width: spineWidth(book) }}
                        >
                          <span className="spine">
                            {known ? <span className="ribbon" style={{ height: `${pct}%` }} aria-hidden="true" /> : null}
                            <span className="spine-title">{title}</span>
                            <span className="spine-foot">
                              <span>{phaseLabel(book.phase) || "未开始"}</span>
                              <span>{count}{book.locked ? " · 占" : ""}</span>
                            </span>
                          </span>
                        </a>
                        <button
                          type="button"
                          className={starred ? "hall-book-menu-btn on" : "hall-book-menu-btn"}
                          aria-expanded={menuDir === book.directory}
                          aria-label={starred ? `《${title}》已收藏，打开收藏和废纸篓` : `打开《${title}》的收藏和废纸篓`}
                          onClick={() => setMenuDir((current) => current === book.directory ? null : book.directory)}
                        >{starred ? "★" : "⋮"}</button>
                        {menuDir === book.directory ? (
                          <div className="hall-book-menu" role="menu">
                            <button
                              type="button"
                              role="menuitem"
                              onClick={() => {
                                toggleStar(book.directory)
                                setMenuDir(null)
                              }}
                            >{starred ? "取消收藏" : "收藏"}</button>
                            <button
                              type="button"
                              role="menuitem"
                              className="danger"
                              onClick={() => discardBook(book.directory)}
                            >放进废纸篓</button>
                          </div>
                        ) : null}
                      </li>
                    )
                  })}
                </ul>
              )}
              <i className="hall-board" aria-hidden="true" />
              <div className="hall-lower">
                <a className="hall-new" href="#/new">+ 新建</a>
                <button className="hall-pick" type="button" disabled={picking} onClick={chooseDirectory}>
                  {picking ? "正在选择目录" : "选择目录"}
                </button>
              </div>
              <i className="hall-board" aria-hidden="true" />
            </div>
          </section>
          <aside className="hall-scroll">
            <p>一书一世界</p>
            <p>一页一人生</p>
          </aside>
        </div>
      </div>
    </div>
  )
}

function ViewIcon({ id }) {
  if (id === "recent") return <ClockIcon />
  if (id === "done") return <CheckIcon />
  if (id === "stars") return <StarIcon />
  return <ShelfIcon />
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="11" cy="11" r="6" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M16 16.5L20 20.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

function WorksIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 5.5h9.5a2 2 0 0 1 2 2V19H8.2A2.2 2.2 0 0 0 6 21.2V5.5z" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M6 19.2A2.2 2.2 0 0 1 8.2 17H17.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  )
}

function PersonIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="8" r="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M6 19c1.2-2.6 3.2-3.8 6-3.8s4.8 1.2 6 3.8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

function ShelfIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 7h14M5 12h14M5 17h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M8 7V4.5h3V7M13 12V9.5h3V12" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  )
}

function ClockIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M12 8.5V12l2.5 2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8.5 12.2l2.3 2.3 4.7-5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

function StarIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 4.5l1.8 4.2 4.6.5-3.4 3.1.9 4.5L12 14.6 8.1 16.8l.9-4.5L5.6 9.2l4.6-.5L12 4.5z" fill="none" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  )
}

function EmptyBooks() {
  return (
    <svg className="hall-still" viewBox="0 0 160 90" aria-hidden="true">
      <path d="M46 62V34h22v28H46z" fill="#efe6d4" />
      <path d="M50 62V38h14v24H50z" fill="#8e2f2a" />
      <path d="M68 62V30h18v32H68z" fill="#2c4a44" />
      <path d="M86 62V36h16v26H86z" fill="#c4a36a" />
      <path d="M38 58h78v6H38z" fill="#f6efe4" />
      <path d="M104 50h28v12H104z" fill="#f3eadc" />
      <path d="M108 46h18v6h-18z" fill="#f7f1e8" />
      <path d="M128 38c6 0 10 8 10 16h-8c0-6-2-10-6-10 2-4 3-6 4-6z" fill="#d9c7aa" />
      <path d="M132 28v12M128 32h8" stroke="#5c4030" strokeWidth="1.4" />
    </svg>
  )
}

function clothsFor(books) {
  const used = []
  return books.map((book) => {
    const text = String(book.directory || "").split(/[\\/]/).filter(Boolean).slice(-2).join("/")
    let n = 0
    for (let i = 0; i < text.length; i += 1) n = (n * 33 + text.charCodeAt(i)) >>> 0
    n %= 6
    let guard = 0
    while (used.includes(n) && guard < 6) {
      n = (n + 1) % 6
      guard += 1
    }
    used.push(n)
    return String(n)
  })
}

function spineWidth(book) {
  const chapters = Math.max(book.total_chapters || 0, book.completed_count || 0)
  return 72 + Math.min(22, Math.round(chapters * 1.4))
}

function Wastebasket({ trash, onRestore, onEmpty }) {
  const [open, setOpen] = useState(false)
  const root = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    function onPointer(event) {
      if (root.current && root.current.contains(event.target)) return
      setOpen(false)
    }
    function onKey(event) {
      if (event.key === "Escape") setOpen(false)
    }
    window.addEventListener("pointerdown", onPointer)
    window.addEventListener("keydown", onKey)
    return () => {
      window.removeEventListener("pointerdown", onPointer)
      window.removeEventListener("keydown", onKey)
    }
  }, [open])
  return (
    <section ref={root} className="basket">
      <button
        type="button"
        className="basket-face"
        aria-expanded={open}
        aria-label={open ? "合上废纸篓" : "打开废纸篓"}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="basket-bin" aria-hidden="true" />
        <span>废纸篓{trash.length ? ` · ${trash.length}` : ""}</span>
      </button>
      {open ? (
        <div className="basket-sheet" role="dialog" aria-label="废纸篓">
          <div className="basket-sheet-head">
            <strong>废纸篓</strong>
            <button type="button" onClick={() => setOpen(false)}>关闭</button>
          </div>
          {trash.length === 0 ? <p>篓里是空的。</p> : (
            <ul>
              {trash.map((book) => {
                const title = book.title || folderName(book.directory)
                return (
                  <li key={book.directory}>
                    <span>{title}</span>
                    <button type="button" onClick={() => onRestore(book.directory)} aria-label={`把《${title}》拣回书架`}>拣回</button>
                  </li>
                )
              })}
            </ul>
          )}
          <button type="button" className="quiet" disabled={trash.length === 0} onClick={onEmpty}>清空废纸篓</button>
          {trash.length > 0 ? <p>目录还留在磁盘上。</p> : null}
        </div>
      ) : null}
    </section>
  )
}

const STYLE_OPTIONS = [
  ["", "不附加"],
  ["default", "default"],
  ["fantasy", "fantasy"],
  ["romance", "romance"],
  ["suspense", "suspense"],
]

export function ModelScreen() {
  const [provider, setProvider] = useState(DEFAULT_PROVIDER)
  const [model, setModel] = useState(DEFAULT_MODEL)
  const [apiKey, setApiKey] = useState("")
  const [apiBase, setApiBase] = useState("")
  const [style, setStyle] = useState("")
  const [keySet, setKeySet] = useState(false)
  const [keyHint, setKeyHint] = useState("")
  const [clearKey, setClearKey] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [owner, setOwner] = useState("")
  const [ready, setReady] = useState(false)
  const [busy, setBusy] = useState(false)
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  useEffect(() => {
    let stop = false
    getModel()
      .then((settings) => {
        if (stop) return
        applySettings(settings, {
          setProvider, setModel, setApiBase, setStyle, setKeySet, setKeyHint, setError,
        })
        setOwner(settings.username || "")
        setReady(Boolean(settings.ready))
        if (!settings.provider) setProvider(DEFAULT_PROVIDER)
        if (!settings.model) setModel(modelForProvider(settings.provider || DEFAULT_PROVIDER, DEFAULT_MODEL))
        setLoaded(true)
      })
      .catch((reason) => {
        if (stop) return
        setProvider(DEFAULT_PROVIDER)
        setModel(DEFAULT_MODEL)
        setError(reason.message)
        setLoaded(true)
      })
    return () => {
      stop = true
    }
  }, [])

  function chooseProvider(event) {
    const next = event.target.value
    setProvider(next)
    setModel((current) => modelForProvider(next, current))
  }

  const providers = providerOptions(provider)
  const models = modelOptions(provider, model)
  const note = providerNote(provider)
  const named = callName(provider, model)
  const styleOptions = STYLE_OPTIONS.some(([value]) => value === style) || !style
    ? STYLE_OPTIONS
    : [[style, style], ...STYLE_OPTIONS]
  const keyNote = keySet
    ? `${keyHint ? `已保存 ${keyHint}` : "已保存"}。留空则保持。`
    : "留空时，调用层按该提供方的环境变量取密钥。"

  function payload() {
    return {
      provider: provider.trim(),
      model: model.trim(),
      api_key: apiKey,
      api_base: apiBase.trim(),
      style,
      clear_key: clearKey && !apiKey.trim(),
    }
  }

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError("")
    setNotice("")
    try {
      const saved = await saveModel(payload())
      applySettings(saved, {
        setProvider, setModel, setApiBase, setStyle, setKeySet, setKeyHint, setError,
      })
      setOwner(saved.username || owner)
      setReady(Boolean(saved.ready))
      setApiKey("")
      setClearKey(false)
      const kept = saved.username ? `已保存到 ${saved.username} 的账号，离开后再进来还是这一份。` : "已保存到当前账号，离开后再进来还是这一份。"
      setNotice(saved.live_stale ? `${kept}当前这次写作仍用原来的模型，结束后换上。` : kept)
    } catch (reason) {
      setError(reason.message)
    } finally {
      setBusy(false)
    }
  }

  async function check() {
    setChecking(true)
    setError("")
    setNotice("")
    try {
      const result = await checkModel(payload())
      if (result.ok) {
        const reply = result.reply ? `应答：${result.reply}` : "模型有应答。"
        setNotice(`检测通过。${reply}`)
      } else {
        setError(result.error || "检测没有通过。")
      }
    } catch (reason) {
      setError(reason.message)
    } finally {
      setChecking(false)
    }
  }

  if (!loaded) {
    return (
      <main className="page narrow">
        <p className="notice" role="status">正在读取模型配置。</p>
      </main>
    )
  }

  return (
    <main className="page narrow">
      <p className="eyebrow"><a href="#/">书架</a></p>
      <h1>接入模型</h1>
      <p className="lede">规划、写作、审阅和裁定共用这一份。它只属于当前账号，写在这个账号的目录里。离开、关掉再进来，还是这一份。页面不显示完整密钥。</p>
      {ready && owner ? <p className="model-line">已绑定 {owner}{named ? ` · ${named}` : ""}</p> : null}
      <form className="model-form" autoComplete="off" onSubmit={submit}>
        <label>
          提供方
          <select value={provider} onChange={chooseProvider} required>
            {providers.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
          {note ? <span className="hint">{note}</span> : null}
        </label>
        <label>
          模型
          <select value={model} onChange={(event) => setModel(event.target.value)} required>
            {models.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
          {named ? <span className="hint">调用名 {named}</span> : null}
        </label>
        <label>
          密钥
          <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={keySet ? "留空则保持现有密钥" : "sk-…"} spellCheck="false" autoComplete="off" />
          <span className="hint">{keyNote}</span>
        </label>
        {keySet && !apiKey.trim() ? (
          <label className="check">
            <input type="checkbox" checked={clearKey} onChange={(event) => setClearKey(event.target.checked)} />
            清除已保存的密钥
          </label>
        ) : null}
        <label>
          接口地址
          <input value={apiBase} onChange={(event) => setApiBase(event.target.value)} placeholder="留空则用该提供方的默认地址" spellCheck="false" />
        </label>
        <label>
          文风
          <select value={style} onChange={(event) => setStyle(event.target.value)}>
            {styleOptions.map(([value, label]) => <option key={value || "none"} value={value}>{label}</option>)}
          </select>
        </label>
        {error ? <p className="banner" role="status">{error}</p> : null}
        {notice ? <p className="banner ok" role="status">{notice}</p> : null}
        <div className="model-actions">
          <button className="signal" type="submit" disabled={busy || checking || !loaded || !provider.trim() || !model.trim()}>
            {busy ? "保存中" : "保存"}
          </button>
          <button className="quiet" type="button" disabled={busy || checking || !loaded || !provider.trim() || !model.trim()} onClick={check}>
            {checking ? "检测中" : "检测"}
          </button>
        </div>
      </form>
    </main>
  )
}

function applySettings(settings, fields) {
  fields.setProvider(settings.provider || "")
  fields.setModel(settings.model || "")
  fields.setApiBase(settings.api_base || "")
  fields.setStyle(settings.style || "")
  fields.setKeySet(Boolean(settings.api_key_set))
  fields.setKeyHint(settings.key_hint || "")
  fields.setError(settings.error || "")
}

export function NewBook({ directory }) {
  const [requirement, setRequirement] = useState("")
  const [path, setPath] = useState(directory || "")
  const [picking, setPicking] = useState(false)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setPath(directory || "")
  }, [directory])

  async function chooseDirectory() {
    setPicking(true)
    setError("")
    try {
      const picked = await pickDirectory()
      if (!picked.cancelled && picked.directory) setPath(picked.directory)
    } catch (reason) {
      setError(reason.message)
    } finally {
      setPicking(false)
    }
  }

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError("")
    try {
      const snap = await sendIntent({ action: "start", requirement: requirement.trim(), directory: path.trim() })
      if (snap.error && !snap.running) {
        setError(snap.error)
        if (snap.directory) setPath(snap.directory)
        return
      }
      window.location.hash = bookHref("/desk", snap.directory)
    } catch (reason) {
      setError(reason.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="page narrow">
      <p className="eyebrow"><a href="#/">书架</a></p>
      <h1>新书</h1>
      <p className="lede">一句话就够。已有进度的目录不会从这里开始，那本用写作现场的继续。</p>
      <form className="new-book" onSubmit={submit}>
        <label>
          需求
          <textarea value={requirement} onChange={(event) => setRequirement(event.target.value)} rows={6} placeholder="一个在雨夜醒来的人" required />
        </label>
        <div className="pick-field">
          <span>目录</span>
          <span className={path ? "path" : "hint"} title={path || undefined}>{path ? shortPath(path) : "不选则新建一个目录"}</span>
          <div className="pick-actions">
            <button className="quiet" type="button" disabled={picking || busy} onClick={chooseDirectory}>
              {picking ? "正在选择目录" : path ? "更换目录" : "选择目录"}
            </button>
            {path ? <button className="quiet" type="button" disabled={busy} onClick={() => setPath("")}>改用新目录</button> : null}
          </div>
        </div>
        {error ? (
          <p className="banner" role="status">
            {error}{" "}
            {error.includes("还没接入模型") ? <a href="#/model">接入模型</a> : null}
            {path && error.includes("继续") ? <a href={bookHref("/desk", path)}>去写作现场</a> : null}
          </p>
        ) : null}
        <button className="signal" type="submit" disabled={busy || !requirement.trim()}>开始</button>
      </form>
    </main>
  )
}

function ProgressBoard({ snapshot }) {
  const view = progressView(snapshot)
  const flow = flowLabel(snapshot.flow)
  const flowNote = flow && flow !== phaseLabel(snapshot.phase) ? flow : ""
  return (
    <section className="progress" aria-label="进度">
      <div className="progress-head">
      <ol className="phase-track">
        {view.phases.map((item) => (
          <li
            key={item.id}
            className={item.state === "current" && snapshot.running ? "current live" : item.state}
            aria-current={item.state === "current" ? "step" : undefined}
          >
            <span>{phaseLabel(item.id)}</span>
          </li>
        ))}
      </ol>
      <p className="progress-count">{progressCaption(view, flowNote)}</p>
      </div>
      {view.marks ? (
        <ol className="chapter-track">
          {view.marks.map((mark) => (
            <li key={mark.n} className={mark.state === "current" && snapshot.running ? "current live" : mark.state}>
              <span>{mark.n}</span>
              <span className="sr">{markLabel(mark)}</span>
            </li>
          ))}
        </ol>
      ) : view.total > 0 ? (
        <div className="chapter-meter" role="img" aria-label={progressCaption(view, "")}>
          <span style={{ width: `${Math.round(view.ratio * 100)}%` }} />
        </div>
      ) : null}
    </section>
  )
}

export function DeskScreen({ directory }) {
  const { snapshot, loadError, setSnapshot } = useSnapshot(directory)
  const [draft, setDraft] = useState("")
  const [busy, setBusy] = useState(false)

  if (!directory) return <MissingBook />
  if (!snapshot) return <Loading message={loadError || "正在读取这本书。"} error={Boolean(loadError)} />

  const view = deskState(snapshot)
  const latestChapter = (snapshot.chapters || []).at(-1) || null
  const pending = snapshot.pending_steer || ""
  const steerText = pending || draft
  const steerOff = blocks(view, "steer") || Boolean(pending) || busy
  const phase = phaseLabel(snapshot.phase)
  const flow = flowLabel(snapshot.flow)

  async function act(action, extra = {}) {
    setBusy(true)
    try {
      const next = await sendIntent({ directory, action, ...extra })
      setSnapshot(next)
      if (action === "steer") setDraft("")
    } catch (reason) {
      setSnapshot({ ...snapshot, error: reason.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="page">
      <header className="page-head">
        <p className="eyebrow">
          <a href="#/">书架</a>
          <span title={snapshot.directory}> · {bookTitle(snapshot)}</span>
        </p>
        <h1>写作现场</h1>
        <p className="lede">{view.sentence}</p>
      </header>
      <BookSwitch directory={directory} current="/desk" importStatus={snapshot.import_status} />
      <div className="section-row desk-meta">
        <div className="desk-pills">
          {snapshot.running ? (
            <span className="pill live">
              <i aria-hidden="true" />
              {phase || "正在写"}
            </span>
          ) : null}
          {flow && flow !== phase ? <span className="pill">{flow}</span> : null}
        </div>
        <div className="desk-mode">
          <div className="mode" role="group" aria-label="推进方式">
            <button type="button" aria-pressed={snapshot.advance_mode === "auto"} disabled={snapshot.locked || busy} onClick={() => snapshot.advance_mode !== "auto" && act("review_off")}>自动推进</button>
            <button type="button" aria-pressed={snapshot.advance_mode === "review"} disabled={snapshot.locked || busy} onClick={() => snapshot.advance_mode !== "review" && act("review_on")}>逐章验收</button>
          </div>
          {snapshot.running && !blocks(view, "abort") ? (
            <button type="button" className="quiet" onClick={() => act("abort")}>暂停</button>
          ) : null}
        </div>
      </div>
      <ProgressBoard snapshot={snapshot} />
      {snapshot.error && view.id !== "config" ? <p className="banner" role="status">{snapshot.error}</p> : null}
      {loadError ? <p className="banner" role="status">{loadError}</p> : null}
      <div className="desk-grid">
        <section>
          <article className="sheet">
            {latestChapter?.title ? <h2 className="chapter-name">{latestChapter.title}</h2> : null}
            {view.id === "config" ? <p className="sheet-next"><a className="signal" href="#/model">接入模型</a></p> : null}
            {snapshot.latest_excerpt ? <Galley text={snapshot.latest_excerpt} bare /> : <h2>{view.sentence}</h2>}
          </article>
          {snapshot.latest_instruction ? (
            <p className="instruction">
              <span>最近一条指令</span>
              {snapshot.latest_instruction.task}
              {snapshot.latest_instruction.reason ? <em>{snapshot.latest_instruction.reason}</em> : null}
            </p>
          ) : null}
          {snapshot.events.length ? <EventList events={snapshot.events} /> : null}
          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault()
              if (view.primary === "steer") {
                if (!steerOff && steerText.trim()) act("steer", { text: steerText })
                return
              }
              if (view.primary === "resume") act("resume")
              if (view.primary === "next") act("next")
              if (view.primary === "import_confirm") act("import_confirm")
            }}
          >
            <h2>干预</h2>
            <label>
              方向
              <textarea
                value={steerText}
                readOnly={Boolean(pending) || blocks(view, "steer")}
                onChange={(event) => setDraft(event.target.value)}
                rows={3}
                placeholder={blocks(view, "steer") ? "现在不能干预" : "写下要改的方向"}
              />
            </label>
            <div className="composer-actions">
              {view.primary === "steer" ? (
                <button className="signal" type="submit" disabled={steerOff || !steerText.trim()}>{view.label}</button>
              ) : null}
              {view.primary && view.primary !== "steer" ? (
                <button className="signal" type="submit" disabled={busy}>{view.label}</button>
              ) : null}
              {view.primary !== "steer" && !blocks(view, "steer") && steerText.trim() ? (
                <button type="button" className="quiet" disabled={steerOff} onClick={() => act("steer", { text: steerText })}>发送干预</button>
              ) : null}
              {view.id === "empty" ? <a className="signal link-button" href={bookHref("/new", directory)}>去写需求</a> : null}
            </div>
          </form>
        </section>
        <aside className="rail" aria-label="这本书">
          <RailItem label="下一章" value={snapshot.next_chapter ? `第 ${snapshot.next_chapter} 章` : "还没有"} dim={!snapshot.next_chapter} />
          {snapshot.pending_rewrites.length ? (
            <RailItem
              label="返工队列"
              value={snapshot.pending_rewrites.map((chapter, index) => `${index === 0 ? "队首 " : ""}第 ${chapter} 章`).join("，")}
            />
          ) : null}
          {snapshot.pause_reason ? <RailItem label="暂停原因" value={snapshot.pause_reason} /> : null}
          {snapshot.advance_hold ? (
            <RailItem
              label="一次性暂停"
              value={`${holdLabel(snapshot.advance_hold.after)}${snapshot.advance_hold.target_chapter ? ` · 第 ${snapshot.advance_hold.target_chapter} 章` : ""} · ${snapshot.advance_hold.reason}`}
            />
          ) : null}
          {snapshot.context_usage ? <RailItem label="上下文占用" value={snapshot.context_usage} /> : null}
          {snapshot.phase === "complete" && snapshot.report ? (
            <div className="fact report-fact">
              <span>完本报告</span>
              <pre className="report">{snapshot.report}</pre>
            </div>
          ) : null}
        </aside>
      </div>
    </main>
  )
}

export function Reader({ directory }) {
  const { snapshot, loadError } = useSnapshot(directory)
  const [current, setCurrent] = useState(null)
  useEffect(() => {
    if (current == null && snapshot?.completed_chapters?.length) {
      setCurrent(snapshot.completed_chapters[0])
    }
  }, [snapshot, current])
  if (!directory) return <MissingBook />
  if (!snapshot) return <Loading message={loadError || "正在读取章节。"} error={Boolean(loadError)} />
  const chapters = new Map(snapshot.chapters.map((chapter) => [chapter.chapter, chapter]))
  const selected = current == null ? null : chapters.get(current)
  return (
    <main className="page reader">
      <header className="page-head">
        <p className="eyebrow"><a href={bookHref("/desk", directory)}>{bookTitle(snapshot)}</a></p>
        <h1>章节阅读</h1>
        <p className="lede">只读。顺序跟已完成章节一致，不能改字，也不能重排。</p>
      </header>
      <BookSwitch directory={directory} current="/read" importStatus={snapshot.import_status} />
      {snapshot.completed_chapters.length === 0 ? <p>还没有完成的章节。</p> : (
        <div className="reader-grid">
          <ol className="chapter-index">
            {snapshot.completed_chapters.map((chapter) => (
              <li key={chapter}>
                <button type="button" aria-current={chapter === current ? "true" : undefined} onClick={() => setCurrent(chapter)}>
                  <span>第 {chapter} 章</span>
                  {chapters.get(chapter)?.title ? <small>{chapters.get(chapter).title}</small> : null}
                </button>
              </li>
            ))}
          </ol>
          <article className="galley reading">
            {selected ? (
              <>
                <h2>{selected.title || `第 ${selected.chapter} 章`}</h2>
                <Galley text={selected.body} bare />
              </>
            ) : (
              <p className="missing">正文缺失</p>
            )}
          </article>
        </div>
      )}
    </main>
  )
}

export function ImportScreen({ directory }) {
  const { snapshot, loadError, setSnapshot } = useSnapshot(directory)
  const [source, setSource] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  if (!directory) return <MissingBook />
  if (!snapshot) return <Loading message={loadError || "正在读取导入状态。"} error={Boolean(loadError)} />
  const view = deskState(snapshot)

  async function act(action, extra = {}) {
    setBusy(true)
    setError("")
    try {
      const next = await sendIntent({ directory, action, ...extra })
      setSnapshot(next)
      if (next.error) setError(next.error)
    } catch (reason) {
      setError(reason.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="page">
      <header className="page-head">
        <p className="eyebrow"><a href={bookHref("/desk", directory)}>{bookTitle(snapshot)}</a></p>
        <h1>导入确认</h1>
        <p className="lede">{snapshot.import_detail || "还没有导入。"}</p>
      </header>
      <BookSwitch directory={directory} current="/import" importStatus={snapshot.import_status} />
      {view.id === "config" ? (
        <p className="banner" role="status">{view.sentence} <a href="#/model">接入模型</a></p>
      ) : null}
      {view.id === "locked" ? <p className="banner" role="status">{view.sentence}</p> : null}
      {error ? <p className="banner" role="status">{error}</p> : null}
      {snapshot.import_chapters.length ? (
        <ol className="titles">
          {snapshot.import_chapters.map((title, index) => <li key={`${title}-${index}`}>{title || "未命名"}</li>)}
        </ol>
      ) : <p className="quiet-text">还没有章节标题。</p>}
      {view.primary === "import_confirm" ? (
        <div className="page-actions">
          <button className="signal" type="button" disabled={busy} onClick={() => act("import_confirm")}>确认切分</button>
        </div>
      ) : null}
      {snapshot.import_status === "working" && !snapshot.running ? (
        <div className="page-actions">
          <button className="signal" type="button" disabled={busy} onClick={() => act("import")}>继续导入</button>
        </div>
      ) : null}
      {snapshot.import_status === "published" ? (
        <p className="banner" role="status">导入已发布，写作尚未继续。回到写作现场后按「继续」。</p>
      ) : null}
      {snapshot.import_status === "" || snapshot.import_status === "failed" ? (
        <form className="attach" onSubmit={(event) => { event.preventDefault(); act("import", { source }) }}>
          <label>
            文本路径
            <input value={source} onChange={(event) => setSource(event.target.value)} placeholder="本机上的小说文本" />
          </label>
          <button className="signal" type="submit" disabled={busy || !source.trim() || !snapshot.config_ready || snapshot.locked}>开始导入</button>
        </form>
      ) : null}
    </main>
  )
}

export function DiagScreen({ directory }) {
  const { snapshot, loadError, setSnapshot } = useSnapshot(directory)
  const [dest, setDest] = useState("")
  const [picking, setPicking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    if (!directory) return undefined
    let stop = false
    sendIntent({ directory, action: "diag" })
      .then((next) => {
        if (!stop) setSnapshot(next)
      })
      .catch((reason) => {
        if (!stop) setError(reason.message)
      })
    return () => {
      stop = true
    }
  }, [directory, setSnapshot])

  if (!directory) return <MissingBook />
  if (!snapshot) return <Loading message={loadError || error || "正在诊断。"} error={Boolean(loadError || error)} />

  async function act(action, extra = {}) {
    setBusy(true)
    setError("")
    try {
      const next = await sendIntent({ directory, action, ...extra })
      setSnapshot(next)
      if (next.error) setError(next.error)
    } catch (reason) {
      setError(reason.message)
    } finally {
      setBusy(false)
    }
  }

  async function chooseFile() {
    setPicking(true)
    setError("")
    try {
      const picked = await pickSaveFile(exportFileName(bookTitle(snapshot)))
      if (!picked.cancelled && picked.path) setDest(picked.path)
    } catch (reason) {
      setError(reason.message)
    } finally {
      setPicking(false)
    }
  }

  return (
    <main className="page">
      <header className="page-head">
        <p className="eyebrow"><a href={bookHref("/desk", directory)}>{bookTitle(snapshot)}</a></p>
        <h1>诊断与导出</h1>
        <p className="lede">只看发现。这里不能修好它，也不能继续写。</p>
      </header>
      <BookSwitch directory={directory} current="/diag" importStatus={snapshot.import_status} />
      {error ? <p className="banner" role="status">{error}</p> : null}
      <div className="diag-grid">
        <section>
          <div className="section-row">
            <h2>发现</h2>
            <button type="button" className="quiet" disabled={busy} onClick={() => act("diag")}>重新诊断</button>
          </div>
          {snapshot.findings.length === 0 ? <p className="quiet-text">没有发现。</p> : (
            <ul className="findings">
              {snapshot.findings.map((item, index) => (
                <li key={`${item.rule}-${item.chapter}-${index}`} className={`finding-${item.severity}`}>
                  <span>{severityLabel(item.severity)}</span>
                  {item.rule} · 第 {item.chapter} 章 · {item.title}
                </li>
              ))}
            </ul>
          )}
          <h2>检查点</h2>
          <p className="quiet-text">按先后记下已经保存的步骤。同一项出现多次，表示后来又保存过。范围是全书时，不对应某一章。</p>
          {snapshot.skeleton.length === 0 ? <p className="quiet-text">没有检查点。</p> : (
            <div className="panel">
              <table className="skeleton">
                <thead>
                  <tr><th>序号</th><th>做了什么</th><th>范围</th><th>章</th></tr>
                </thead>
                <tbody>
                  {snapshot.skeleton.map((item) => (
                    <tr key={item.seq}>
                      <td>{item.seq}</td>
                      <td>{stepLabel(item.step)}</td>
                      <td>{scopeLabel(item.scope)}</td>
                      <td>{item.chapter ? `第 ${item.chapter} 章` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <form className="export" onSubmit={(event) => { event.preventDefault(); act("export", { dest }) }}>
          <h2>导出</h2>
          <div className="pick-field">
            <span>保存为</span>
            <span className={dest ? "path" : "hint"} title={dest || undefined}>{dest ? shortPath(dest) : "还没选择文件"}</span>
            <div className="pick-actions">
              <button className="quiet" type="button" disabled={picking || busy} onClick={chooseFile}>
                {picking ? "正在选择文件" : dest ? "更换文件" : "选择文件"}
              </button>
            </div>
          </div>
          <button className="signal" type="submit" disabled={busy || picking || !dest}>导出</button>
          {snapshot.exported_path ? <p>已写出 {snapshot.exported_path}</p> : null}
        </form>
      </div>
    </main>
  )
}

function Galley({ text, bare = false }) {
  const paragraphs = String(text || "").split(/\n+/).filter((line) => line.trim())
  return (
    <div className={bare ? "galley-body" : "galley"}>
      {paragraphs.map((paragraph, index) => (
        <p key={index} className={sceneBreak(paragraph) ? "scene" : undefined}>{paragraph}</p>
      ))}
    </div>
  )
}

function sceneBreak(text) {
  const line = text.trim()
  return line.length > 0 && line.length <= 8 && !/[。！？，、；：]/.test(line)
}

function EventList({ events }) {
  return (
    <section className="event-block">
      <h3>事件</h3>
      {events.length === 0 ? <p className="quiet-text empty-events">尚无事件</p> : (
        <ol className="events">
          {events.map((event, index) => <li key={`${index}-${event}`}>{event}</li>)}
        </ol>
      )}
    </section>
  )
}

function RailItem({ label, value, dim = false }) {
  return (
    <div className="fact">
      <span>{label}</span>
      <strong className={dim ? "dim" : undefined}>{value}</strong>
    </div>
  )
}

export function ListingScreen({ directory }) {
  const { snapshot, loadError, setSnapshot } = useSnapshot(directory)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState("")
  const [error, setError] = useState("")

  useEffect(() => {
    if (!directory) return undefined
    let stop = false
    sendIntent({ directory, action: "listing" })
      .then((next) => {
        if (!stop) setSnapshot(next)
      })
      .catch((reason) => {
        if (!stop) setError(reason.message)
      })
    return () => {
      stop = true
    }
  }, [directory, setSnapshot])

  if (!directory) return <MissingBook />
  if (!snapshot) return <Loading message={loadError || error || "正在生成投稿资料。"} error={Boolean(loadError || error)} />
  const card = snapshot.listing

  async function refresh() {
    setBusy(true)
    setError("")
    setCopied("")
    try {
      const next = await sendIntent({ directory, action: "listing" })
      setSnapshot(next)
      if (next.error) setError(next.error)
    } catch (reason) {
      setError(reason.message)
    } finally {
      setBusy(false)
    }
  }

  async function copy(label, text) {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(label)
      setError("")
    } catch (reason) {
      setError(reason.message || "复制没有完成")
    }
  }

  const names = card?.protagonists || []
  return (
    <main className="page">
      <header className="page-head">
        <p className="eyebrow"><a href={bookHref("/desk", directory)}>{bookTitle(snapshot)}</a></p>
        <h1>投稿资料</h1>
        <p className="lede">按创建作品那一页来：书名不超过 15 字，主角名不超过 5 字，简介 50 到 500 字。封面提示词可以直接贴进生图。标签到网站的下拉里选最接近的一项。</p>
      </header>
      <BookSwitch directory={directory} current="/listing" importStatus={snapshot.import_status} />
      {error ? <p className="banner" role="status">{error}</p> : null}
      {card?.note ? <p className="banner" role="status">{card.note}</p> : null}
      {!card ? <p className="quiet-text">还没有生成。</p> : (
        <div className="panel listing">
          <CopyRow label="书本名称" value={card.title} copied={copied} onCopy={copy} />
          <CopyRow label="目标读者" value={card.audience} copied={copied} onCopy={copy} />
          <CopyRow label="阅读标签" value={card.reading_tag} copied={copied} onCopy={copy} />
          <CopyRow label="内容标签" value={card.content_tag} copied={copied} onCopy={copy} />
          <CopyRow label="主角名 1" value={names[0] || ""} copied={copied} onCopy={copy} />
          <CopyRow label="主角名 2" value={names[1] || ""} copied={copied} onCopy={copy} />
          <CopyRow label="作品简介" value={card.synopsis} copied={copied} onCopy={copy} count={card.synopsis_count} />
          <CopyRow label="封面提示词" value={card.cover_prompt} copied={copied} onCopy={copy} />
          <div className="page-actions">
            <button className="signal" type="button" disabled={busy} onClick={refresh}>{busy ? "正在生成" : "重新生成"}</button>
          </div>
        </div>
      )}
    </main>
  )
}

function CopyRow({ label, value, count, copied, onCopy }) {
  const empty = !value
  return (
    <div className="listing-row">
      <div className="listing-label">
        <span>{label}</span>
        {count != null ? <em className={count < 50 || count > 500 ? "dim" : undefined}>{count}/500</em> : null}
      </div>
      <p className={empty ? "hint" : undefined}>{empty ? "没有" : value}</p>
      <button className="quiet" type="button" disabled={empty} onClick={() => onCopy(label, value)}>
        {copied === label ? "已复制" : "复制"}
      </button>
    </div>
  )
}

function BookSwitch({ directory, current, importStatus = "" }) {
  const showImport = current === "/import" || importStatus === "await_confirmation" || importStatus === "working" || importStatus === "failed"
  const items = [
    ["/desk", "写作现场"],
    ["/read", "章节阅读"],
    ...(showImport ? [["/import", "导入确认"]] : []),
    ["/diag", "诊断与导出"],
    ["/listing", "投稿资料"],
  ]
  return (
    <nav className="book-switch" aria-label="这本书">
      {items.map(([path, label]) => (
        <a key={path} href={bookHref(path, directory)} aria-current={current === path ? "page" : undefined}>{label}</a>
      ))}
    </nav>
  )
}

function Loading({ message, error }) {
  return (
    <main className="page">
      <p className={error ? "banner" : "notice"} role="status">{message}</p>
    </main>
  )
}

function MissingBook() {
  return (
    <main className="page narrow">
      <h1>没有选中的书</h1>
      <p className="lede">从书架再选一本。</p>
      <div className="page-actions">
        <a className="signal" href="#/">回书架</a>
      </div>
    </main>
  )
}
