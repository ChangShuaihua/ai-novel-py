"""无界面入口。缺配置时直接失败，并指向用户目录。"""

import argparse
import sys
from pathlib import Path

from ainovel.host.config import ConfigError
from ainovel.host.host import Host, HostError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ainovel")
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start")
    start.add_argument("directory")
    start.add_argument("requirement")

    resume = commands.add_parser("resume")
    resume.add_argument("directory")

    continue_book = commands.add_parser("continue")
    continue_book.add_argument("directory")

    steer = commands.add_parser("steer")
    steer.add_argument("directory")
    steer.add_argument("text")

    abort = commands.add_parser("abort")
    abort.add_argument("directory")

    review = commands.add_parser("review")
    review.add_argument("directory")
    review.add_argument("mode", choices=("on", "off"))

    nxt = commands.add_parser("next")
    nxt.add_argument("directory")

    diag = commands.add_parser("diag")
    diag.add_argument("directory")

    export = commands.add_parser("export")
    export.add_argument("directory")
    export.add_argument("dest")

    evaluate = commands.add_parser("eval")
    evaluate.add_argument("directory")
    evaluate.add_argument("--left", default="")
    evaluate.add_argument("--right", required=True)

    tui = commands.add_parser("tui")
    tui.add_argument("directory")

    web = commands.add_parser("web")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)

    import_book = commands.add_parser("import")
    import_book.add_argument("directory")
    import_book.add_argument("source")
    import_book.add_argument("--yes", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "diag":
        from ainovel.diag import diagnose, render_diagnosis

        print(render_diagnosis(diagnose(args.directory)))
        return 0
    if args.command == "export":
        from ainovel.exporting import export_txt

        print(export_txt(args.directory, args.dest))
        return 0
    if args.command == "eval":
        from pathlib import Path

        from ainovel.evalrun import compare_styles

        result = compare_styles(Path(args.directory), args.left, args.right)
        print("same" if result["same"] else "different")
        return 0
    if args.command == "tui":
        from ainovel.entry.tui import run_tui

        run_tui(args.directory)
        return 0
    if args.command == "web":
        from ainovel.entry.web import serve

        serve(host=args.host, port=args.port)
        return 0
    if args.command == "import":
        from ainovel.host.config import load_config
        from ainovel.host.host import completer_from_config
        from ainovel.importers.pipeline import ImportError as ImportFailed
        from ainovel.importers.pipeline import ingest, run

        root = Path(args.directory)
        source = Path(args.source)
        root.mkdir(parents=True, exist_ok=True)
        try:
            if not (root / "meta" / "import" / "source.txt").is_file():
                ingest(root, source.name, source.read_text(encoding="utf-8"), auto_confirm=args.yes)
            result = run(root, completer_from_config(load_config()), accept=args.yes)
        except (ConfigError, ImportFailed, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(result["status"])
        return 0
    try:
        host = Host.open(args.directory)
        try:
            if args.command == "start":
                result = host.start(args.requirement)
            elif args.command == "resume":
                result = host.resume()
            elif args.command == "continue":
                result = host.continue_book()
            elif args.command == "steer":
                result = host.steer(args.text)
            elif args.command == "review":
                host.set_advance_mode("review" if args.mode == "on" else "auto")
                print("逐章验收" if args.mode == "on" else "自动推进")
                return 0
            elif args.command == "next":
                result = host.advance_one_chapter()
            else:
                host.abort()
                print("已请求暂停")
                return 0
        finally:
            host.close()
    except (ConfigError, HostError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if result.report:
        print(result.report)
    elif result.reason:
        print(result.reason)
    else:
        print(result.status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
