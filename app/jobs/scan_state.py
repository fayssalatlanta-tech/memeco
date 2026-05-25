"""
In-memory scan state shared between request handlers and async workers.

Single source of truth for the dashboard's Scan Monitor. All access must go
through the helpers here so the underlying lock stays consistent.

The module also exposes a tiny pub/sub registry so the SSE endpoint can
push live updates to connected browsers instead of forcing them to poll.
"""

from __future__ import annotations

import asyncio
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

# Per-subscriber queues. Each connected SSE client owns one queue;
# update_scan_state / append_scan_step fan events out to every queue.
# The queues are bounded so a slow client cannot grow memory unbounded.
_SUBSCRIBERS_LOCK = threading.Lock()
_SUBSCRIBERS: list[asyncio.Queue] = []
_SUBSCRIBER_QUEUE_MAX = 64


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_scan_state() -> dict:
    with SCAN_LOCK:
        return dict(SCAN_STATE)


def update_scan_state(**updates) -> None:
    with SCAN_LOCK:
        SCAN_STATE.update(updates)
        snapshot = dict(SCAN_STATE)
    _broadcast({"type": "scan_state", "data": snapshot})


def append_scan_step(name: str, status: str, message: str | None = None) -> None:
    step = {
        "name": name,
        "status": status,
        "message": message,
        "at": utc_now_iso(),
    }
    with SCAN_LOCK:
        steps = list(SCAN_STATE.get("steps") or [])
        steps.append(step)
        SCAN_STATE["steps"] = steps[-20:]
        snapshot = dict(SCAN_STATE)
    # Send both granular (step) and full snapshot (state) so subscribers
    # can choose what to react to.
    _broadcast({"type": "scan_step", "data": step})
    _broadcast({"type": "scan_state", "data": snapshot})


# ---- Pub/sub for SSE -----------------------------------------------------


def subscribe() -> asyncio.Queue:
    """Register a new SSE subscriber and return its event queue."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAX)
    with _SUBSCRIBERS_LOCK:
        _SUBSCRIBERS.append(queue)
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    """Drop a subscriber. Safe to call multiple times."""
    with _SUBSCRIBERS_LOCK:
        try:
            _SUBSCRIBERS.remove(queue)
        except ValueError:
            pass


def _broadcast(event: dict[str, Any]) -> None:
    """Push ``event`` onto every subscriber queue.

    Designed to be safe to call from any context: async coroutines on the
    main loop, threaded background workers, even sync code that has no
    loop at all. We schedule the put_nowait on each queue's owning loop
    via ``call_soon_threadsafe``, which is correct whether the caller is
    on that loop or not. If a subscriber's queue is full the event is
    dropped (the client will reconnect and resync via the next snapshot).
    """
    with _SUBSCRIBERS_LOCK:
        subs = list(_SUBSCRIBERS)
    if not subs:
        return

    for queue in subs:
        # asyncio.Queue records its owning loop at creation. Use the
        # documented helper if available; fall back to the underscore
        # attribute on older runtimes.
        loop = getattr(queue, "_loop", None)
        if loop is None:
            try:
                loop = queue._get_loop()  # type: ignore[attr-defined]
            except Exception:
                continue
        if loop is None or loop.is_closed():
            continue
        try:
            loop.call_soon_threadsafe(_safe_put_nowait, queue, event)
        except RuntimeError:
            continue


def _safe_put_nowait(queue: asyncio.Queue, event: dict[str, Any]) -> None:
    if queue.full():
        return
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        pass
