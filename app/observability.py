"""Structured JSONL event log. Secrets are redacted before anything touches disk or the console."""
from __future__ import annotations

import json
import logging
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_SENSITIVE_KEY = re.compile(r"(api[_-]?key|token|password|secret|authorization|cookie)", re.I)
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.I)
_KEYISH = re.compile(r"\b(sk-[A-Za-z0-9_\-]{12,}|ghp_[A-Za-z0-9]{20,})\b")

log = logging.getLogger("frontend_agent")


def redact(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if _SENSITIVE_KEY.search(str(k)) else redact(v, secrets)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        s = _KEYISH.sub("***", _BEARER.sub(r"\1***", value))
        for sec in secrets:
            if sec:
                s = s.replace(sec, "***")
        return s
    return value


class EventLog:
    def __init__(self, path: Path | None = None, secrets: tuple[str, ...] = ()):
        self.path = path
        self.secrets = secrets
        self.events: list[dict] = []
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, **fields: Any) -> dict:
        rec = redact({"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "event": event, **fields}, self.secrets)
        self.events.append(rec)
        line = json.dumps(rec, default=str)
        log.info(line if len(line) < 400 else line[:400] + "...")
        if self.path:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return rec

    @contextmanager
    def stage(self, name: str, **fields: Any) -> Iterator[dict]:
        t0 = time.monotonic()
        self.emit("stage_start", stage=name, **fields)
        extra: dict = {}
        try:
            yield extra
        except Exception as e:
            self.emit("stage_failed", stage=name, duration_s=round(time.monotonic() - t0, 3), error=type(e).__name__, message=str(e)[:500])
            raise
        self.emit("stage_done", stage=name, duration_s=round(time.monotonic() - t0, 3), **extra)
