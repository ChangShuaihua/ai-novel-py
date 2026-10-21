"""终端界面只订阅宿主事件。这里不调用工具，也不读路由。"""

from pathlib import Path


def format_events(events: list[str]) -> str:
    if not events:
        return "尚无事件"
    return "\n".join(events)


def run_tui(directory: str) -> None:
    try:
        from textual.app import App, ComposeResult
        from textual.widgets import RichLog, Static
    except ImportError as exc:
        raise SystemExit("终端界面需要安装 textual") from exc

    from ainovel.host.host import Host

    class NovelApp(App):
        def __init__(self, host: Host) -> None:
            super().__init__()
            self.host = host

        def compose(self) -> ComposeResult:
            yield Static("ainovel")
            yield RichLog(id="events")

        def on_mount(self) -> None:
            log = self.query_one("#events", RichLog)
            log.write(format_events(self.host.engine.events))

            def listener(text: str) -> None:
                log.write(text)

            self.host.subscribe(listener)

    host = Host.open(Path(directory))
    try:
        NovelApp(host).run()
    finally:
        host.close()
