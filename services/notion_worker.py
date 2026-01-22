from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Callable, Iterable


@dataclass
class NotionJobResult:
    status: str
    payload: dict | None = None


class NotionWorker:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, task: Callable[[threading.Event], None]) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=task, args=(self._stop_event,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self.running:
            self._stop_event.set()


def connect_to_notion(token: str, database_url: str) -> tuple[str, str]:
    return "notion_database", database_url


def validate_notion_schema(database_id: str) -> tuple[bool, str | None]:
    return True, None


def fetch_database_rows(database_id: str) -> Iterable[dict]:
    time.sleep(0.2)
    return []
