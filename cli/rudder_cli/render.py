"""Printing. Two shapes: a padded table for humans, ``json.dumps`` for scripts.

``--json`` exists because ``rudder status`` and the list commands are things
scripts read. It is literally ``json.dumps`` — no formatter framework.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import Any


def out(line: str = "") -> None:
    print(line)


def err(line: str) -> None:
    print(line, file=sys.stderr)


def emit_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


def table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    if not rows:
        out("(none)")
        return
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    out(fmt.format(*headers).rstrip())
    out(fmt.format(*("-" * w for w in widths)).rstrip())
    for row in rows:
        out(fmt.format(*row).rstrip())
