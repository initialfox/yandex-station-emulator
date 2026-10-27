#!/usr/bin/env python3
"""Tail QEMU serial log → viewer /api/event (state=boot)."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
VIEWER = os.environ.get('ALICE_VIEWER_URL', "http://127.0.0.1:8765/api/event")
FLUSH_EVERY = 0.12
MAX_CHUNK = 1800


def post(payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        VIEWER,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=2).read()
    except (urllib.error.URLError, TimeoutError, OSError):
        pass


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: console_tail.py <console.log>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)

    buf: list[str] = []
    last_flush = time.monotonic()
    pos = 0

    def flush(force: bool = False) -> None:
        nonlocal buf, last_flush
        now = time.monotonic()
        if not buf:
            return
        if not force and (now - last_flush) < FLUSH_EVERY and sum(len(x) for x in buf) < MAX_CHUNK:
            return
        chunk = "".join(buf)
        buf = []
        last_flush = now
        chunk = ANSI.sub("", chunk).replace("\r\n", "\n").replace("\r", "\n")
        # drop empty
        lines = [ln for ln in chunk.split("\n") if ln.strip()]
        if not lines:
            return
        # batch as one chunk for fewer SSE events
        text = "\n".join(lines[-80:])
        post({"state": "boot", "chunk": text})

    # если лог уже есть (reboot mid-flight) — сначала докинем хвост
    try:
        existing = path.read_bytes()
        if existing:
            chunk = ANSI.sub("", existing.decode("utf-8", errors="replace"))
            chunk = chunk.replace("\r\n", "\n").replace("\r", "\n")
            lines = [ln for ln in chunk.split("\n") if ln.strip()]
            if lines:
                post({"state": "boot", "chunk": "\n".join(lines[-120:])})
            pos = path.stat().st_size
    except OSError:
        pass

    # follow; на truncate (новый boot) — читаем с нуля
    while True:
        try:
            with path.open("rb") as f:
                f.seek(pos)
                while True:
                    data = f.read(4096)
                    if not data:
                        flush(force=True)
                        time.sleep(0.08)
                        try:
                            size = path.stat().st_size
                        except OSError:
                            size = 0
                        if size < pos:
                            pos = 0
                            f.seek(0)
                            post({"state": "boot", "chunk": "— serial reset —"})
                        else:
                            pos = f.tell()
                        continue
                    text = data.decode("utf-8", errors="replace")
                    buf.append(text)
                    pos = f.tell()
                    flush()
        except FileNotFoundError:
            time.sleep(0.2)
        except KeyboardInterrupt:
            flush(force=True)
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
