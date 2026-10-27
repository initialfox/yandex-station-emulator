#!/usr/bin/env python3
"""Watch fake Mini2 LED sysfs → POST /api/event (ring + matrix) to viewer."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

VIEWER = os.environ.get('ALICE_VIEWER_URL', "http://127.0.0.1:8765/api/event")
POLL = 0.2
MIN_POST_INTERVAL = 0.5  # ≤2 Hz — иначе валит HTTP-сервер

DIGIT_MAP = {
    frozenset("ABCDEF"): "0",
    frozenset("BC"): "1",
    frozenset("ABDEG"): "2",
    frozenset("ABCDG"): "3",
    frozenset("BCFG"): "4",
    frozenset("ACDFG"): "5",
    frozenset("ACDEFG"): "6",
    frozenset("ABC"): "7",
    frozenset("ABCDEFG"): "8",
    frozenset("ABCDFG"): "9",
    frozenset("G"): "-",
    frozenset(): " ",
}


def read_bri(path: Path) -> int:
    try:
        return max(0, min(255, int(path.read_text().strip() or "0")))
    except Exception:
        return 0


def post(payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(
        VIEWER, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        urllib.request.urlopen(req, timeout=1.5).read()
    except (urllib.error.URLError, TimeoutError, OSError):
        pass


def decode_digit(root: Path, pos: int) -> str:
    on = []
    for s in "ABCDEFG":
        if read_bri(root / f"mini2:white:clock{s}{pos}" / "brightness") > 8:
            on.append(s)
    return DIGIT_MAP.get(frozenset(on), "?")


def decode_clock(root: Path) -> tuple[str, bool]:
    d1, d2, d3, d4 = (decode_digit(root, i) for i in (1, 2, 3, 4))
    colon = (
        read_bri(root / "mini2:white:clockPLUS1" / "brightness") > 8
        or read_bri(root / "mini2:white:clockPLUS2" / "brightness") > 8
    )
    degree = read_bri(root / "mini2:white:clockDEGREE" / "brightness") > 8
    mid = ":" if colon else " "
    text = f"{d1}{d2}{mid}{d3}{d4}".replace(" ", "")
    # keep HH:MM shape for matrix font
    if len(text) < 4:
        text = f"{d1}{d2}:{d3}{d4}"
    else:
        text = f"{d1}{d2}{mid}{d3}{d4}"
    return text, degree


def snapshot(root: Path) -> dict:
    ring = []
    for i in range(1, 7):
        r = read_bri(root / f"mini2:red:ring{i}" / "brightness")
        g = read_bri(root / f"mini2:green:ring{i}" / "brightness")
        b = read_bri(root / f"mini2:blue:ring{i}" / "brightness")
        ring.append(f"#{r:02x}{g:02x}{b:02x}")

    segs = {}
    for p in root.glob("mini2:white:clock*/brightness"):
        name = p.parent.name.split("clock", 1)[-1]
        segs[name] = read_bri(p)

    clock, degree = decode_clock(root)
    # infer coarse state from ring average brightness / hue
    state = "hw"
    avg = sum(int(c[i : i + 2], 16) for c in ring for i in (1, 3, 5)) / (6 * 3)
    if avg < 4:
        ui = "idle"
    else:
        # purple-ish → listen/speak heuristic
        rs = [int(c[1:3], 16) for c in ring]
        gs = [int(c[3:5], 16) for c in ring]
        bs = [int(c[5:7], 16) for c in ring]
        if sum(bs) > sum(rs) + sum(gs):
            ui = "listen"
        elif sum(gs) > sum(rs):
            ui = "speak"
        elif sum(rs) > 80 and sum(gs) > 60:
            ui = "think"
        else:
            ui = "listen"

    return {
        "state": "hw",
        "ui": ui,
        "ring": ring,
        "segs": segs,
        "clock": clock,
        "degree": degree,
        "message": f"leds avg={avg:.0f}",
    }


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "led_sysfs")
    if not root.is_dir():
        print(f"no led sysfs: {root}", file=sys.stderr)
        return 1
    last = ""
    last_post = 0.0
    while True:
        snap = snapshot(root)
        # не тащим огромный segs в SSE каждый кадр — только кольцо+часы
        light = {
            "state": snap["state"],
            "ui": snap["ui"],
            "ring": snap["ring"],
            "clock": snap["clock"],
            "degree": snap["degree"],
            "segs": snap["segs"],
            "message": snap["message"],
        }
        key = json.dumps(light, sort_keys=True)
        now = time.monotonic()
        if key != last and (now - last_post) >= MIN_POST_INTERVAL:
            last = key
            last_post = now
            post(light)
        time.sleep(POLL)


if __name__ == "__main__":
    raise SystemExit(main())
