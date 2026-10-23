/** 同一时刻取第一条匹配的状态。错误短摘要不改变主按钮。 */

export function deskState(snapshot) {
  const phase = snapshot.phase || ""
  const running = Boolean(snapshot.running)
  const rewrites = snapshot.pending_rewrites || []
  const hold = snapshot.advance_hold
  const mode = snapshot.advance_mode || ""
  const permit = Number(snapshot.advance_permit_chapter || 0)

  if (!snapshot.config_ready) {
    return view(
      "config",
      "还没接入模型。需要模型的动作先停在这里。",
      null,
      "",
      ["start", "resume", "steer", "next", "import_confirm"],
    )
  }
  if (snapshot.locked) {
    return view(
      "locked",
      `目录被占用。锁在 ${snapshot.lock_path}`,
      null,
      "",
      ["start", "resume", "steer", "abort", "next"],
    )
  }
  if (snapshot.import_status === "await_confirmation") {
    return view("import", "切分已经准备好，等你看过再确认。", "import_confirm", "确认切分", ["next"])
  }
  if (snapshot.import_status === "working") {
    return view("import_working", snapshot.import_detail || "导入仍在进行", null, "", ["next"])
  }
  if (phase === "complete") {
    return view("complete", "这本书已经写完。", null, "", ["start", "next"])
  }
  if (rewrites.length) {
    return view(
      "rewrite",
      running ? "返工进行中。" : "返工还没继续。",
      running ? "steer" : "resume",
      running ? "发送干预" : "继续",
      ["next"],
    )
  }
  if (mode === "review" && phase === "writing" && !running && permit === 0 && !hold) {
    const completed = snapshot.completed_chapters || []
    const latest = completed.length ? Math.max(...completed) : 0
    const sentence =
      latest === 0
        ? `规划已就绪，逐章验收等待放行第 ${snapshot.next_chapter} 章`
        : `已完成至第 ${latest} 章，逐章验收等待放行第 ${snapshot.next_chapter} 章`
    return view("permit", sentence, "next", "放行下一章", [])
  }
  if (snapshot.paused && hold) {
    return view("hold", "写作停在边界。", "resume", "继续", ["next"])
  }
  if (phase === "init" || phase === "premise" || phase === "outline") {
    return view(
      "plan",
      running ? "规划进行中。" : "规划停在这里。",
      running ? "steer" : "resume",
      running ? "发送干预" : "继续",
      ["next"],
    )
  }
  if (mode === "auto" && phase === "writing" && running) {
    return view("auto", "正在自动写作。", "steer", "发送干预", ["next"])
  }
  if (phase === "writing" && running) {
    return view("writing", "正在写作。", "steer", "发送干预", ["next"])
  }
  if (!running && phase) {
    return view("idle", "写作停在这里。", "resume", "继续", ["next"])
  }
  return view("empty", "还没有进度。", null, "", ["resume", "steer", "next"])
}

export function blocks(state, action) {
  return state.disabled.includes(action)
}

function view(id, sentence, primary, label, disabled) {
  return { id, sentence, primary, label, disabled }
}
