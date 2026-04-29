"""
scheduler.py
────────────
Stores delayed/batched notifications in a JSON queue and automatically
delivers them after focus hours end. Also handles spam: spam notifications
are stored separately and never delivered.

Auto-delivery rule (simple & robust):
    Every 30 seconds: if queue is not empty AND current hour is NOT a
    focus hour → flush all queued items via WebSocket immediately.
"""

import asyncio, json, os, time

QUEUE_FILE = "data/logs/scheduled_queue.json"
SPAM_FILE  = "data/logs/spam_log.json"

_broadcast_fn    = None
_get_focus_hours = None


def init_scheduler(broadcast_fn, get_focus_hours_fn):
    global _broadcast_fn, _get_focus_hours
    _broadcast_fn    = broadcast_fn
    _get_focus_hours = get_focus_hours_fn


def _load_queue() -> list:
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_queue(items: list):
    os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
    with open(QUEUE_FILE, "w") as f:
        json.dump(items, f)


def _load_spam_log() -> list:
    if os.path.exists(SPAM_FILE):
        try:
            with open(SPAM_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_spam_log(items: list):
    os.makedirs(os.path.dirname(SPAM_FILE), exist_ok=True)
    with open(SPAM_FILE, "w") as f:
        json.dump(items, f)


def schedule_notification(action: str, summary: str, payload: dict = None):
    if action == "spam":
        log = _load_spam_log()
        log.append({
            "summary":    summary,
            "payload":    payload or {},
            "blocked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        if len(log) > 200:
            log = log[-200:]
        _save_spam_log(log)
        print(f"[SPAM BLOCKED] {summary[:80]}")
        return

    if action in ("delay", "batch"):
        queue = _load_queue()
        queue.append({
            "summary":    summary,
            "payload":    payload or {},
            "action":     action,
            "queued_at":  time.time(),
            "queued_str": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        _save_queue(queue)
        print(f"[SCHEDULED/{action.upper()}] {summary[:80]}")
        return

    print(f"[{action.upper()}] {summary[:80]}")


def get_scheduled_queue() -> list:
    return _load_queue()


def get_spam_log() -> list:
    return _load_spam_log()


async def flush_scheduled_queue() -> int:
    queue = _load_queue()
    if not queue:
        return 0
    if _broadcast_fn:
        for item in queue:
            await _broadcast_fn({
                "type":      "scheduled_notification",
                "summary":   item["summary"],
                "action":    item["action"],
                "payload":   item.get("payload", {}),
                "queued_at": item.get("queued_str", ""),
                "delivered": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            await asyncio.sleep(0.05)
    count = len(queue)
    _save_queue([])
    print(f"[SCHEDULER] Flushed {count} queued notification(s)")
    return count


async def start_scheduler_loop():
    await asyncio.sleep(5)
    print("[SCHEDULER] Background loop started")
    while True:
        try:
            queue        = _load_queue()
            focus_hours  = _get_focus_hours() if _get_focus_hours else []
            current_hour = int(time.strftime("%H"))
            in_focus     = current_hour in focus_hours
            if queue and not in_focus:
                print(f"[SCHEDULER] Outside focus hours ({current_hour}:xx) — auto-delivering {len(queue)} item(s)")
                await flush_scheduled_queue()
        except Exception as e:
            print(f"[SCHEDULER] Loop error: {e}")
        await asyncio.sleep(30)
