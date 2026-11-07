"""把正在生成的文字送给已经打开的页面。"""

import queue
import threading


class LiveFeed:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._text: dict[str, str] = {}
        self._listeners: dict[str, list[queue.Queue]] = {}

    def reset(self, key: str) -> None:
        self._publish(key, "", reset=True)

    def push(self, key: str, text: str) -> None:
        if text:
            self._publish(key, text, reset=False)

    def text(self, key: str) -> str:
        with self._lock:
            return self._text.get(key, "")

    def events(self, key: str):
        box: queue.Queue = queue.Queue()
        with self._lock:
            self._listeners.setdefault(key, []).append(box)
            current = self._text.get(key, "")
        try:
            yield {"reset": True, "text": current}
            while True:
                try:
                    item = box.get(timeout=12)
                except queue.Empty:
                    yield {"ping": True}
                    continue
                yield item
        finally:
            with self._lock:
                listeners = self._listeners.get(key, [])
                if box in listeners:
                    listeners.remove(box)

    def _publish(self, key: str, text: str, *, reset: bool) -> None:
        with self._lock:
            if reset:
                self._text[key] = ""
            else:
                self._text[key] = self._text.get(key, "") + text
            listeners = list(self._listeners.get(key, ()))
        event = {"reset": True, "text": ""} if reset else {"reset": False, "text": text}
        for box in listeners:
            box.put(event)
