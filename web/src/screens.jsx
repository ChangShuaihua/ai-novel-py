import { cloneElement, useEffect, useId, useRef, useState } from "react"

import { bookHref, checkModel, currentUsername, emptyTrash, getLibrary, getModel, moveBook, pickSaveFile, saveModel, sendIntent, useSnapshot } from "./api.js"
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
import { assistView } from "./assist.js"
import { formatOutline, parseOutline, reorder } from "./beats.js"
import { bookTitle, exportFileName, flowLabel, folderName, holdLabel, phaseLabel, shortPath } from "./labels.js"
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

function readShelfView() {
  const query = (window.location.hash.split("?")[1] || "")
  const view = new URLSearchParams(query).get("shelf")
  return ["recent", "done", "stars"].includes(view) ? view : "all"
}

function openShelf(id, setView) {
  setView(id)
  const next = id === "all" ? "#/" : `#/?shelf=${id}`
  if (window.location.hash !== next) window.location.hash = next
}

function wantsSearch() {
  return new URLSearchParams(window.location.hash.split("?")[1] || "").get("search") === "1"
}

let libraryCache = null

function useLibrary() {
  const [library, setLibraryState] = useState(libraryCache)
  const [loadError, setLoadError] = useState("")
  function setLibrary(next) {
    libraryCache = next
    setLibraryState(next)
  }
  useEffect(() => {
    let stop = false
    let timer = 0
    async function tick() {
      try {
        const next = await getLibrary()
        if (!stop) {
          setLibrary(next)
          setLoadError("")
        }
      } catch (reason) {
        if (!stop) setLoadError(reason.message)
      } finally {
        if (!stop) timer = window.setTimeout(tick, 2000)
      }
    }
    tick()
    return () => {
      stop = true
      window.clearTimeout(timer)
    }
  }, [])
  return { library, setLibrary, loadError }
}

function ModelStatus({ library }) {
  if (!library) return null
  if (!library.config_ready) {
    return (
      <p className="banner" role="status">
        还没接入模型。需要模型的动作先停在这里。 <a href="#/model">接入模型</a>
      </p>
    )
  }
  if (!library.model_label) return null
  return <p className="model-line">当前模型 {library.model_label} · <a href="#/model">更换</a></p>
}

function HallTop({ here, onLeave, children }) {
  const [accountOpen, setAccountOpen] = useState(false)
  useEffect(() => {
    if (!accountOpen) return undefined
    function close() { setAccountOpen(false) }
    window.addEventListener("pointerdown", close)
    return () => window.removeEventListener("pointerdown", close)
  }, [accountOpen])
  return (
    <header className="hall-bar">
      <a className="mark" href="#/">
        <span className="seal" aria-hidden="true">文</span>
        <span className="mark-name">ainovel</span>
      </a>
      <span className="hall-here">{here}</span>
      <a className="hall-create" href="#/new" aria-current={here === "新书" ? "page" : undefined}>
        <PenIcon /> 新书创作
      </a>
      <div className="hall-tools">
        {children}
        <div className="hall-account" onPointerDown={(event) => event.stopPropagation()}>
          <button type="button" className="hall-tool" aria-expanded={accountOpen} onClick={() => setAccountOpen((open) => !open)}>
            <PersonIcon /> {currentUsername() || "登录"}
          </button>
          {accountOpen ? (
            <div className="hall-pop">
              <a href="#/model" aria-current={here === "接入模型" ? "page" : undefined}>接入模型</a>
              <a href="#/pass">改密码</a>
              <button type="button" onClick={onLeave}>离开</button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  )
}

function HallMenu({ active, view, onView, trash, onRestore, onEmpty }) {
  const onShelf = active === "shelf"
  return (
    <nav className="hall-menu" aria-label="书架分类">
      {onShelf ? (
        <button type="button" aria-current={view === "all" ? "true" : undefined} onClick={() => onView("all")}>
          <ShelfIcon /> 我的书架
        </button>
      ) : (
        <a href="#/"><ShelfIcon /> 我的书架</a>
      )}
      <a href="#/new" aria-current={active === "new" ? "page" : undefined}><PenIcon /> 新书创作</a>
      {SHELF_VIEWS.filter(([id]) => id !== "all").map(([id, label]) => (
        onShelf ? (
          <button key={id} type="button" aria-current={view === id ? "true" : undefined} onClick={() => onView(id)}>
            <ViewIcon id={id} /> {label}
          </button>
        ) : (
          <a key={id} href={`#/?shelf=${id}`}><ViewIcon id={id} /> {label}</a>
        )
      ))}
      <Wastebasket trash={trash} onRestore={onRestore} onEmpty={onEmpty} />
    </nav>
  )
}

export function Shelf({ onLeave }) {
  const { library, setLibrary, loadError } = useLibrary()
  const [actionError, setActionError] = useState("")
  const [view, setView] = useState(readShelfView)
  const [query, setQuery] = useState("")
  const [searching, setSearching] = useState(wantsSearch)
  const [stars, setStars] = useState(readStars)
  const [menuDir, setMenuDir] = useState(null)

  useEffect(() => {
    const sync = () => {
      setView(readShelfView())
      if (wantsSearch()) setSearching(true)
    }
    window.addEventListener("hashchange", sync)
    return () => window.removeEventListener("hashchange", sync)
  }, [])

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
    setStars((current) => {
      const next = current.filter((item) => item !== directory)
      try { localStorage.setItem(STARRED, JSON.stringify(next)) } catch { /* 记不住时，这一页仍可看 */ }
      return next
    })
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
      <HallTop here="书架" onLeave={onLeave}>
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
      </HallTop>
      <div className="hall-stage">
        <header className="hall-title">
          <h1>书架<span className="hall-seal" aria-hidden="true">架</span></h1>
          <p>每本书只回答现在写到哪。点进去，再决定下一步谁动。</p>
        </header>
        <ModelStatus library={library} />
        {actionError || loadError ? <p className="banner" role="status">{actionError || loadError}</p> : null}
        <div className="hall-body">
          <HallMenu
            active="shelf"
            view={view}
            onView={(id) => openShelf(id, setView)}
            trash={trash}
            onRestore={restoreBook}
            onEmpty={clearTrash}
          />
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
                    const href = bookHref("/desk", book.directory)
                    const title = shelfTitle(book)
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
                          title={title}
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
                <a className="hall-new" href="#/new">新书创作</a>
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

function purgeLabel(value) {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  return `${date.getMonth() + 1}月${date.getDate()}日自动清空`
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
                const title = shelfTitle(book)
                const due = purgeLabel(book.purge_at)
                return (
                  <li key={book.directory}>
                    <span className="basket-book">
                      <span>{title}</span>
                      {due ? <small>{due}</small> : null}
                    </span>
                    <button type="button" onClick={() => onRestore(book.directory)} aria-label={`把《${title}》拣回书架`}>拣回</button>
                  </li>
                )
              })}
            </ul>
          )}
          <button type="button" className="quiet" disabled={trash.length === 0} onClick={onEmpty}>清空废纸篓</button>
          {trash.length > 0 ? <p>已不在书架上。满三天自动删除，也可以现在清空。</p> : null}
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

export function ModelScreen({ onLeave }) {
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
      <StudioFrame here="接入模型" title="接入模型" seal="模" lede="规划、写作和修改共用这一份。密钥只留在当前账号，页面不显示完整密钥。" active="model" onLeave={onLeave}>
        <section className="manuscript">
          <p className="manuscript-wait" role="status">正在读取模型配置。</p>
        </section>
      </StudioFrame>
    )
  }

  return (
    <StudioFrame here="接入模型" title="接入模型" seal="模" lede="规划、写作和修改共用这一份。密钥只留在当前账号，页面不显示完整密钥。" active="model" onLeave={onLeave}>
      <form className="manuscript" autoComplete="off" onSubmit={submit}>
        {ready && owner ? <p className="model-bound">已绑定 {owner}{named ? ` · ${named}` : ""}</p> : null}
        <Field label="提供方" hint={note}>
          <select value={provider} onChange={chooseProvider} required>
            {providers.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </Field>
        <Field label="模型" hint={named ? `调用名 ${named}` : ""}>
          <select value={model} onChange={(event) => setModel(event.target.value)} required>
            {models.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </Field>
        <Field label="密钥" hint={keyNote}>
          <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={keySet ? "留空则保持现有密钥" : "sk-…"} spellCheck="false" autoComplete="off" />
        </Field>
        {keySet && !apiKey.trim() ? (
          <label className="draft-check model-clear">
            <input type="checkbox" checked={clearKey} onChange={(event) => setClearKey(event.target.checked)} />
            清除已保存的密钥
          </label>
        ) : null}
        <Field label="接口地址">
          <input value={apiBase} onChange={(event) => setApiBase(event.target.value)} placeholder="留空则用该提供方的默认地址" spellCheck="false" />
        </Field>
        <Field label="文风">
          <select value={style} onChange={(event) => setStyle(event.target.value)}>
            {styleOptions.map(([value, label]) => <option key={value || "none"} value={value}>{label}</option>)}
          </select>
        </Field>
        {error ? <p className="banner" role="status">{error}</p> : null}
        {notice ? <p className="banner ok" role="status">{notice}</p> : null}
        <div className="manuscript-foot">
          <button className="manuscript-side" type="button" disabled={busy || checking || !provider.trim() || !model.trim()} onClick={check}>
            {checking ? "检测中" : "检测"}
          </button>
          <button className="manuscript-create" type="submit" disabled={busy || checking || !provider.trim() || !model.trim()}>
            {busy ? "保存中" : "保存"}
          </button>
        </div>
      </form>
    </StudioFrame>
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

function shelfTitle(book) {
  if (book.title) return book.title
  if (String(book.directory || "").startsWith("db:")) return "未命名"
  return folderName(book.directory)
}

function StudioFrame({ here, title, seal, lede, active, onLeave, children }) {
  const { library, setLibrary } = useLibrary()
  const [basketError, setBasketError] = useState("")

  async function restoreBook(directory) {
    setBasketError("")
    try {
      setLibrary(await moveBook(directory, "restore"))
    } catch (reason) {
      setBasketError(reason.message)
    }
  }

  async function clearTrash() {
    setBasketError("")
    try {
      setLibrary(await emptyTrash())
    } catch (reason) {
      setBasketError(reason.message)
    }
  }

  return (
    <div className="hall">
      <HallTop here={here} onLeave={onLeave}>
        <a className="hall-tool" href="#/?search=1"><SearchIcon /> 搜索</a>
        <a className="hall-tool" href="#/"><WorksIcon /> 我的作品</a>
      </HallTop>
      <div className="hall-stage">
        <header className="hall-title">
          <h1>{title}<span className="hall-seal" aria-hidden="true">{seal}</span></h1>
          <p>{lede}</p>
        </header>
        <ModelStatus library={library} />
        {basketError ? <p className="banner" role="status">{basketError}</p> : null}
        <div className="hall-body">
          <HallMenu
            active={active}
            trash={library?.trash || []}
            onRestore={restoreBook}
            onEmpty={clearTrash}
          />
          <div className="hall-sheet">{children}</div>
          <aside className="hall-scroll">
            <p>一书一世界</p>
            <p>一页一人生</p>
          </aside>
        </div>
      </div>
    </div>
  )
}

function Field({ label, count, extra, hint, children }) {
  const id = useId()
  return (
    <div className="manuscript-field">
      <div className="field-label">
        <label htmlFor={id}>{label}</label>
        {extra}
        {count ? <span className="field-count">{count}</span> : null}
      </div>
      {cloneElement(children, { id })}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </div>
  )
}

function PenIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 19l2.2-.4L17.8 8.1a1.6 1.6 0 0 0 0-2.3l-.6-.6a1.6 1.6 0 0 0-2.3 0L4.4 15.8 5 19z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M13.8 6.2l3 3" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  )
}

function QuillIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 18c4-1 8-6 10-12 1 6-1 11-6 13" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M8 16l4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

const DRAFT_KEY = "ainovel-new-draft"

function readDraft() {
  try {
    const parsed = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null")
    if (!parsed || typeof parsed !== "object") return null
    return parsed
  } catch {
    return null
  }
}

export function NewBook({ directory, onLeave }) {
  const linked = String(directory || "").startsWith("db:") ? directory : ""
  const saved = readDraft()
  const [title, setTitle] = useState(saved?.title || "")
  const [synopsis, setSynopsis] = useState(saved?.synopsis || "")
  const [chapter, setChapter] = useState(saved?.chapter || "")
  const [keepDraft, setKeepDraft] = useState(Boolean(saved?.keep))
  const [bookId, setBookId] = useState(linked)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setBookId(linked)
  }, [linked])

  useEffect(() => {
    if (!keepDraft) {
      localStorage.removeItem(DRAFT_KEY)
      return
    }
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ title, synopsis, chapter, keep: true }))
  }, [keepDraft, title, synopsis, chapter])

  const seed = [chapter.trim(), synopsis.trim(), title.trim()].filter(Boolean).join("\n")

  async function submit(event) {
    event?.preventDefault()
    if (!seed) {
      setError("先写下标题、简介，或这一章想写的内容。")
      return
    }
    setBusy(true)
    setError("")
    try {
      const snap = await sendIntent({
        action: "start",
        requirement: seed,
        title: title.trim(),
        synopsis: synopsis.trim(),
        directory: bookId,
      })
      if (snap.error && !snap.running) {
        if (String(snap.directory || "").startsWith("db:")) setBookId(snap.directory)
        setError(snap.error)
        return
      }
      if (!keepDraft) localStorage.removeItem(DRAFT_KEY)
      window.location.hash = bookHref("/desk", snap.directory)
    } catch (reason) {
      setError(reason.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <StudioFrame here="新书" title="新书" seal="新" lede="一段故事，从这里开始。" active="new" onLeave={onLeave}>
      <form className="manuscript" onSubmit={submit}>
        <Field label="小说标题" count={`${title.length}/24`}>
          <input value={title} maxLength={24} placeholder="请输入作品标题，24字以内" disabled={busy} onChange={(event) => setTitle(event.target.value)} />
        </Field>
        <Field label="小说简介" count={`${synopsis.length}/1000`}>
          <textarea value={synopsis} maxLength={1000} rows={4} placeholder="请输入作品简介，支持 Markdown" disabled={busy} onChange={(event) => setSynopsis(event.target.value)} />
        </Field>
        <Field
          label="章节内容"
          extra={<button type="button" className="field-ai" disabled={busy || !seed} onClick={submit}>AI 生成</button>}
        >
          <textarea value={chapter} rows={8} placeholder="开始写作吧..." disabled={busy} onChange={(event) => setChapter(event.target.value)} />
        </Field>
        {error ? (
          <p className="banner" role="status">
            {error}{" "}
            {error.includes("还没接入模型") ? <a href="#/model">接入模型</a> : null}
            {bookId && error.includes("继续") ? <a href={bookHref("/desk", bookId)}>回到这本</a> : null}
          </p>
        ) : null}
        <div className="manuscript-foot">
          <label className="draft-check">
            <input type="checkbox" checked={keepDraft} disabled={busy} onChange={(event) => setKeepDraft(event.target.checked)} />
            保存草稿
          </label>
          <button className="manuscript-create" type="submit" disabled={busy || !seed}>
            <QuillIcon /> {busy ? "生成中" : "开始创作"}
          </button>
        </div>
      </form>
    </StudioFrame>
  )
}

function ProgressBoard({ snapshot, focus = 0, onPick }) {
  const view = progressView(snapshot)
  const tip = focus || view.written || 0
  const span = view.total > 1 ? `${Math.max(0, (tip - 1) / (view.total - 1)) * 100}%` : "0%"
  return (
    <>
      <nav className="phase-nav" aria-label="创作阶段">
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
      </nav>
      <div className="chapter-progress">
        {view.marks ? (
          <ol className="chapter-track" style={{ "--progress": span }} aria-label="章节进度">
            {view.marks.map((mark) => {
              const shown = focus === mark.n ? { ...mark, state: "current" } : mark
              const live = shown.state === "current" && snapshot.running
              const pick = onPick && (mark.state === "done" || mark.state === "rewrite" || focus === mark.n)
              return (
                <li key={mark.n} className={live ? "current live" : shown.state}>
                  {pick ? (
                    <button type="button" aria-current={focus === mark.n ? "true" : undefined} onClick={() => onPick(mark.n)}>{mark.n}</button>
                  ) : <span>{mark.n}</span>}
                  <span className="sr">{markLabel(shown)}</span>
                </li>
              )
            })}
          </ol>
        ) : view.total > 0 ? (
          <div className="chapter-meter" role="img" aria-label={progressCaption(view, "")}>
            <span style={{ width: `${Math.round(view.ratio * 100)}%` }} />
          </div>
        ) : <p className="quiet-text">章数还没定</p>}
      </div>
    </>
  )
}

function BookBoard({ directory, snapshot, current, lede, focus = 0, onPick, extra }) {
  const phase = phaseLabel(snapshot.phase)
  const flow = flowLabel(snapshot.flow)
  return (
    <section className="desk-board" aria-label="作品进度">
      <header className="work-info">
        <div className="work-copy">
          <p className="eyebrow"><a href="#/">书架</a></p>
          <h1>{bookTitle(snapshot)}</h1>
          {lede ? <p className="lede">{lede}</p> : null}
        </div>
        <div className="work-count">
          <p>{progressCaption(progressView(snapshot), flow && flow !== phase ? flow : "")}</p>
          {extra}
        </div>
        <BookSwitch directory={directory} current={current} importStatus={snapshot.import_status} />
      </header>
      <ProgressBoard snapshot={snapshot} focus={focus} onPick={onPick} />
    </section>
  )
}

export function DeskScreen({ directory, onLeave }) {
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

  const guiding = Boolean(snapshot.guide && view.id === "guide")

  return (
    <div className="room desk-room">
    <header className="appbar">
      <a className="mark" href="#/">
        <span className="seal" aria-hidden="true">案</span>
        <span className="mark-name">ainovel</span>
      </a>
      <span className="appbar-here">写作现场</span>
      <div className="appbar-actions">
        <a className="appbar-model" href="#/model">接入模型</a>
        <a className="appbar-model" href="#/pass">改密码</a>
        {onLeave ? <button type="button" className="appbar-leave" onClick={onLeave}>离开</button> : null}
      </div>
    </header>
    <main className="page">
      <BookBoard
        directory={directory}
        snapshot={snapshot}
        current="/desk"
        lede={view.sentence}
        focus={guiding && snapshot.guide.stage === "chapter" ? snapshot.guide.chapter : 0}
        extra={(
          <>
            {snapshot.running ? (
              <span className="pill live"><i aria-hidden="true" />{phase || "正在写"}</span>
            ) : null}
            {view.id === "guide" ? null : (
              <div className="mode" role="group" aria-label="推进方式">
                <button type="button" aria-pressed={snapshot.advance_mode === "auto"} disabled={snapshot.locked || busy} onClick={() => snapshot.advance_mode !== "auto" && act("review_off")}>自动推进</button>
                <button type="button" aria-pressed={snapshot.advance_mode === "review"} disabled={snapshot.locked || busy} onClick={() => snapshot.advance_mode !== "review" && act("review_on")}>逐章验收</button>
              </div>
            )}
            {snapshot.running && !blocks(view, "abort") ? (
              <button type="button" className="quiet" onClick={() => act("abort")}>暂停</button>
            ) : null}
          </>
        )}
      />
      {!guiding && snapshot.error && view.id !== "config" ? <p className="banner" role="status">{snapshot.error}</p> : null}
      {!guiding && loadError ? <p className="banner" role="status">{loadError}</p> : null}
      <div className="desk-grid">
        <section>
          {guiding ? (
            <GuideStep guide={snapshot.guide} busy={busy || snapshot.running} error={snapshot.error || loadError} onAct={act} />
          ) : (
            <>
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
            </>
          )}
        </section>
        <Assistant snapshot={snapshot} />
      </div>
    </main>
    </div>
  )
}

let beatSerial = 0

function stampOutline(text) {
  const items = parseOutline(text)
  if (!items.length) items.push({ title: "", summary: "" })
  return items.map((item, index) => ({
    id: `o${beatSerial += 1}`,
    title: item.title,
    summary: item.summary,
    open: index === 0,
  }))
}

function BeatList({ items, disabled, onChange, addLabel, placeholder }) {
  const [over, setOver] = useState(-1)

  function move(from, to) {
    onChange(reorder(items, from, to))
  }

  function patch(index, fields) {
    onChange(items.map((item, i) => (i === index ? { ...item, ...fields } : item)))
  }

  function add() {
    onChange([...items, { id: `o${beatSerial += 1}`, title: "", summary: "", open: true }])
  }

  function remove(index) {
    if (items.length <= 1) return
    onChange(items.filter((_, i) => i !== index))
  }

  return (
    <div className="beat-editor">
      <ol className="beat-list">
        {items.map((item, index) => (
          <li
            key={item.id}
            className={over === index ? "beat is-over" : "beat"}
            onDragOver={(event) => {
              if (disabled) return
              event.preventDefault()
              setOver(index)
            }}
              onDrop={(event) => {
                event.preventDefault()
                const from = Number(event.dataTransfer.getData("text/plain"))
                if (!Number.isNaN(from)) move(from, index)
                setOver(-1)
              }}
            >
            <button
              type="button"
              className="beat-handle"
              draggable={!disabled}
              disabled={disabled}
              aria-label={`第 ${index + 1} 条，拖拽排序，上下键也可以移动`}
              onDragStart={(event) => {
                event.dataTransfer.effectAllowed = "move"
                event.dataTransfer.setData("text/plain", String(index))
              }}
                onDragEnd={() => setOver(-1)}
                onKeyDown={(event) => {
                if (event.key === "ArrowUp") {
                  event.preventDefault()
                  move(index, index - 1)
                }
                if (event.key === "ArrowDown") {
                  event.preventDefault()
                  move(index, index + 1)
                }
              }}
            >
              <span aria-hidden="true" />
            </button>
            <span className="beat-no">{String(index + 1).padStart(2, "0")}</span>
            <div className="beat-main">
              <div className="beat-line">
                <input
                  value={item.title}
                  disabled={disabled}
                  placeholder="章节标题"
                  aria-label={`第 ${index + 1} 章标题`}
                  onChange={(event) => patch(index, { title: event.target.value })}
                />
                <span className="beat-tools">
                  <button type="button" className="beat-fold" aria-expanded={item.open} onClick={() => patch(index, { open: !item.open })}>
                    {item.open ? "收起" : "展开"}
                  </button>
                  {items.length > 1 ? (
                    <button type="button" className="beat-remove" disabled={disabled} onClick={() => remove(index)}>去掉</button>
                  ) : null}
                </span>
              </div>
              {item.open ? (
                <textarea
                  value={item.summary}
                  rows={3}
                  disabled={disabled}
                  placeholder={placeholder}
                  aria-label={`第 ${index + 1} 章发生的事`}
                  onChange={(event) => patch(index, { summary: event.target.value })}
                />
              ) : <p className="beat-closed">{item.summary || "还没有这一章的事"}</p>}
            </div>
          </li>
        ))}
      </ol>
      <button type="button" className="beat-add" disabled={disabled} onClick={add}>{addLabel}</button>
    </div>
  )
}

function Assistant({ snapshot }) {
  const guide = snapshot.guide
  const latest = (snapshot.chapters || []).at(-1)
  const writing = guide && (guide.stage === "chapter" || guide.stage === "done")
  const view = assistView({
    outline: guide?.outline || [],
    chapter: writing ? guide.chapter : 0,
    body: (writing ? guide.chapter_body : "") || latest?.body || "",
    synopsis: guide?.synopsis || "",
    stage: guide?.stage || "",
    completed: snapshot.completed_chapters || [],
    instruction: snapshot.latest_instruction?.task || "",
  })
  const ratio = view.total ? Math.round((view.written / view.total) * 100) : 0
  return (
    <aside className="rail assistant" aria-label="创作助手">
      <h2>创作助手</h2>
      <section>
        <h3>大纲完成度</h3>
        {view.total ? (
          <>
            <p className="assist-ratio">{view.written} / {view.total} 章已写完</p>
            <div className="assist-meter" aria-hidden="true"><span style={{ width: `${ratio}%` }} /></div>
            <ol className="assist-outline">
              {view.items.map((item) => (
                <li key={item.n} className={item.state}>
                  <span>{item.n}</span>
                  <span>
                    {item.title || "未命名"}
                    {item.state === "current" && item.summary ? <small>{item.summary}</small> : null}
                  </span>
                </li>
              ))}
            </ol>
          </>
        ) : <p className="quiet-text">还没有大纲。</p>}
      </section>
      <section>
        <h3>人物关系</h3>
        {view.people.length ? (
          <ul className="assist-names">{view.people.map((name) => <li key={name}>{name}</li>)}</ul>
        ) : <p className="quiet-text">正文里还没有对上人名。</p>}
        {view.relations.length ? (
          <ul className="assist-relations">
            {view.relations.map((item) => <li key={item}>同一段里有 {item}</li>)}
          </ul>
        ) : null}
      </section>
      <section>
        <h3>剧情伏笔</h3>
        {view.plants.length ? (
          <ul className="assist-plants">
            {view.plants.map((item) => (
              <li key={`${item.chapter}-${item.note}`}>
                <span>第 {item.chapter} 章 {item.title}</span>
                <small>{item.note}</small>
              </li>
            ))}
          </ul>
        ) : <p className="quiet-text">后面的章节还没和这一章对上。</p>}
      </section>
      <section>
        <h3>建议</h3>
        <ul className="assist-notes">
          {view.notes.map((note) => <li key={note}>{note}</li>)}
        </ul>
      </section>
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
  )
}

function GuideStep({ guide, busy, error, onAct }) {
  const [title, setTitle] = useState(guide.title || "")
  const [synopsis, setSynopsis] = useState(guide.synopsis || "")
  const [outline, setOutline] = useState(guide.outline_text || "")
  const [outlineBeats, setOutlineBeats] = useState(() => stampOutline(guide.outline_text))
  const [chapterTitle, setChapterTitle] = useState(guide.chapter_title || "")
  const [chapterBody, setChapterBody] = useState(guide.chapter_body || "")
  const [note, setNote] = useState("")

  useEffect(() => {
    setTitle(guide.title || "")
    setSynopsis(guide.synopsis || "")
    setOutline(guide.outline_text || "")
    setOutlineBeats(stampOutline(guide.outline_text))
    setChapterTitle(guide.chapter_title || "")
    setChapterBody(guide.chapter_body || "")
    setNote("")
  }, [guide.revision])

  const stage = guide.stage
  const heading = stage === "title" ? "新书" : stage === "outline" ? "大纲" : stage === "done" ? "最后一章" : `第 ${guide.chapter} 章`
  const seal = stage === "title" ? "题目" : stage === "outline" ? "大纲" : stage === "done" ? "完" : "本章"
  let label = "确认并生成大纲"
  if (stage === "title" && !guide.title) label = "生成题目"
  if (stage === "outline") label = "确认并写第一章"
  if (stage === "chapter") label = guide.remaining > 0 ? "确认并写下一章" : "确认这一章"
  if (stage === "done") label = ""

  function confirm(event) {
    event.preventDefault()
    if (stage === "title") onAct("guide_confirm", { title: title.trim(), synopsis: synopsis.trim() })
    if (stage === "outline") onAct("guide_confirm", { outline_text: outline })
    if (stage === "chapter") onAct("guide_confirm", { chapter_title: chapterTitle.trim(), chapter_body: chapterBody })
  }

  function revise() {
    onAct("guide_revise", { text: note.trim(), chapter_title: chapterTitle.trim(), chapter_body: chapterBody })
  }

  function changeOutline(next) {
    setOutlineBeats(next)
    setOutline(formatOutline(next))
  }

  return (
    <form className={stage === "outline" ? "manuscript in-desk is-outline" : "manuscript in-desk"} onSubmit={confirm}>
      <div className="guide-title">
        <h2>{heading}<i>{seal}</i></h2>
      </div>
      {stage === "title" ? (
        <>
          <Field label="小说标题" count={`${title.length}/24`}>
            <input value={title} maxLength={24} placeholder="请输入作品标题，24字以内" disabled={busy} onChange={(event) => setTitle(event.target.value)} />
          </Field>
          <Field label="小说简介" count={`${synopsis.length}/1000`}>
            <textarea value={synopsis} maxLength={1000} rows={4} placeholder="请输入作品简介，支持 Markdown" disabled={busy} onChange={(event) => setSynopsis(event.target.value)} />
          </Field>
        </>
      ) : null}
      {stage === "outline" ? (
        <div className="manuscript-field">
          <div className="field-label"><span>大纲</span></div>
          <BeatList
            items={outlineBeats}
            disabled={busy}
            onChange={changeOutline}
            addLabel="加一章"
            placeholder="这一章发生的事"
          />
        </div>
      ) : null}
      {stage === "chapter" || stage === "done" ? (
        <>
          <Field label="章节标题">
            <input value={chapterTitle} disabled={busy} onChange={(event) => setChapterTitle(event.target.value)} />
          </Field>
          <Field
            label="章节内容"
            extra={<button type="button" className="field-ai" disabled={busy || !note.trim()} onClick={revise}>{busy ? "生成中" : "AI 修改"}</button>}
          >
            <textarea className="chapter-body" value={chapterBody} rows={16} placeholder="开始写作吧..." disabled={busy || stage === "done"} onChange={(event) => setChapterBody(event.target.value)} />
          </Field>
          <Field label="交给 AI 的修改要求">
            <textarea value={note} rows={3} placeholder="把雨夜改成清晨" disabled={busy} onChange={(event) => setNote(event.target.value)} />
          </Field>
        </>
      ) : null}
      {error ? <p className="banner" role="status">{error}</p> : null}
      <div className="manuscript-foot">
        <span />
        {label ? (
          <button className="manuscript-create" type="submit" disabled={busy || (stage === "title" && guide.title && (!title.trim() || !synopsis.trim())) || (stage === "outline" && !outline.trim())}>
            <QuillIcon /> {busy ? "生成中" : label}
          </button>
        ) : null}
      </div>
    </form>
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
  const done = new Set(snapshot.completed_chapters)
  const outline = snapshot.guide?.outline || []
  const catalog = outline.length
    ? outline.map((item) => ({
      n: Number(item.chapter),
      title: chapters.get(Number(item.chapter))?.title || item.title || "",
      ready: done.has(Number(item.chapter)),
    }))
    : snapshot.completed_chapters.map((n) => ({ n, title: chapters.get(n)?.title || "", ready: true }))
  return (
    <main className="page reader">
      <BookBoard
        directory={directory}
        snapshot={snapshot}
        current="/read"
        lede={selected ? `第 ${selected.chapter} 章${selected.title ? ` · ${selected.title}` : ""}` : "还没有写完的章节。"}
        focus={current || 0}
        onPick={setCurrent}
      />
      {snapshot.completed_chapters.length === 0 ? <p className="quiet-text board-follow">还没有完成的章节。</p> : (
        <div className="desk-grid">
          <article className="sheet reading">
            {selected ? (
              <>
                <h2 className="chapter-name">{selected.title || `第 ${selected.chapter} 章`}</h2>
                <div className="chapter-read">{selected.body}</div>
              </>
            ) : (
              <p className="missing">正文缺失</p>
            )}
          </article>
          <nav className="chapter-index" aria-label="目录">
            <h2>目录</h2>
            <ol>
              {catalog.map((item) => (
                <li key={item.n}>
                  {item.ready ? (
                    <button type="button" aria-current={item.n === current ? "true" : undefined} onClick={() => setCurrent(item.n)}>
                      <span>第 {item.n} 章</span>
                      {item.title ? <small>{item.title}</small> : null}
                    </button>
                  ) : (
                    <p className="catalog-wait">
                      <span>第 {item.n} 章</span>
                      {item.title ? <small>{item.title}</small> : null}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          </nav>
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
  const [job, setJob] = useState("")
  const [copied, setCopied] = useState("")
  const [error, setError] = useState("")
  const [dest, setDest] = useState("")
  const [picking, setPicking] = useState(false)
  const busy = job !== ""

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
    setJob("listing")
    setError("")
    setCopied("")
    try {
      const next = await sendIntent({ directory, action: "listing" })
      setSnapshot(next)
      if (next.error) setError(next.error)
    } catch (reason) {
      setError(reason.message)
    } finally {
      setJob("")
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

  async function exportBook(event) {
    event.preventDefault()
    setJob("export")
    setError("")
    try {
      const next = await sendIntent({ directory, action: "export", dest })
      setSnapshot(next)
      if (next.error) setError(next.error)
    } catch (reason) {
      setError(reason.message)
    } finally {
      setJob("")
    }
  }

  const names = card?.protagonists || []
  return (
    <main className="page">
      <BookBoard
        directory={directory}
        snapshot={snapshot}
        current="/listing"
        lede="书名不超过 15 字，主角名不超过 5 字，简介 50 到 500 字。封面提示词可以直接贴进生图。"
      />
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
            <button className="signal" type="button" disabled={busy || picking} onClick={refresh}>{job === "listing" ? "正在生成" : "重新生成"}</button>
          </div>
        </div>
      )}
      <form className="export" onSubmit={exportBook}>
        <h2>导出正文</h2>
        <div className="pick-field">
          <span>保存为</span>
          <span className={dest ? "path" : "hint"} title={dest || undefined}>{dest ? shortPath(dest) : "还没选择文件"}</span>
          <div className="pick-actions">
            <button className="quiet" type="button" disabled={picking || busy} onClick={chooseFile}>
              {picking ? "正在选择文件" : dest ? "更换文件" : "选择文件"}
            </button>
          </div>
        </div>
        <button className="signal" type="submit" disabled={busy || picking || !dest}>{job === "export" ? "导出中" : "导出"}</button>
        {snapshot.exported_path ? <p>已写出 {snapshot.exported_path}</p> : null}
      </form>
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
