"""
In-memory scan state shared between request handlers and async workers.

Single source of truth for the dashboard's Scan Monitor. All access must go
through the helpers here so the underlying lock stays consistent.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

SCAN_LOCK = threading.Lock()
SCAN_STATE: dict[str, Any] = {
    "running": False,
    "status": "idle",
    "stage": "idle",
    "message": "No scan has been started",
    "started_at": None,
    "finished_at": None,
    "error": None,
    "steps": [],
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_scan_state() -> dict:
    with SCAN_LOCK:
        return dict(SCAN_STATE)


def update_scan_state(**updates) -> None:
    with SCAN_LOCK:
        SCAN_STATE.update(updates)


def append_scan_step(name: str, status: str, message: str | None = None) -> None:
    with SCAN_LOCK:
        steps = list(SCAN_STATE.get("steps") or [])
        steps.append(
            {
                "name": name,
                "status": status,
                "message": message,
                "at": utc_now_iso(),
            }
        )
        SCAN_STATE["steps"] = steps[-20:]
