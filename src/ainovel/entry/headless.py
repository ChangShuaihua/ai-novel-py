"""无界面入口。缺配置时直接失败，并指向用户目录。"""

import argparse
import sys

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

    args = parser.parse_args(argv)
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
