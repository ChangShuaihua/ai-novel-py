"""时间字段使用 RFC3339。"""

from datetime import datetime, timezone


def parse_time(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "." in text:
        head, tail = text.split(".", 1)
        digits: list[str] = []
        index = 0
        while index < len(tail) and tail[index].isdigit():
            if len(digits) < 6:
                digits.append(tail[index])
            index += 1
        frac = "".join(digits).ljust(6, "0")
        text = f"{head}.{frac}{tail[index:]}"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def dump_time(value: datetime) -> str:
    moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc).replace(microsecond=0)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
