from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
import json, os, asyncio, socket, datetime
from typing import List

from app.core.pipeline import run_pipeline
from app.context.collector import collect_context
from app.api import routes_dataset
from app.models.priority_model import retrain, predict_priority
from app.context.encoder import encode_context
from app.core.decision_engine import decide_action
from app.core.rl_engine import get_rl_adjustment, record_feedback as rl_record, get_rl_summary, reset_rl
from app.models.smart_bundler import bundle_notifications
from app.core.spam_detector import detect_spam, DEFAULT_SPAM_KEYWORDS
from app.core.scheduler import (
    init_scheduler, start_scheduler_loop,
    get_scheduled_queue, flush_scheduled_queue,
    get_spam_log, schedule_notification,
)

app = FastAPI(title="NeuralNotify – Context-Aware Notification System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATS_FILE      = "data/logs/stats.json"
PRIORITIES_FILE = "data/logs/user_priorities.json"

os.makedirs("data/logs",    exist_ok=True)
os.makedirs("data/uploads", exist_ok=True)

DEFAULT_PRIORITIES = {
    "vipPersons": [],
    "appWeights": {
        "whatsapp": 70, "gmail": 65, "slack": 80,
        "instagram": 20, "twitter": 15, "youtube": 10,
        "sms": 75, "phone": 90
    },
    "keywords":       ["urgent", "deadline", "emergency", "asap", "critical"],
    "focusHours":     [9, 10, 11, 14, 15, 16],
    "thresholdSend":  70,
    "thresholdDelay": 40,
    "spamKeywords":   [],   # user-added spam keywords (merged with built-ins)
    "spamEnabled":    True,
}


# ── helpers ───────────────────────────────────────────────────────────────
def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE) as f:
            return json.load(f)
    return {"total": 0, "send_now": 0, "delay": 0, "batch": 0,
            "feedback": [], "history": []}

def save_stats(s):
    with open(STATS_FILE, "w") as f:
        json.dump(s, f)

def load_priorities():
    if os.path.exists(PRIORITIES_FILE):
        with open(PRIORITIES_FILE) as f:
            return json.load(f)
    return DEFAULT_PRIORITIES.copy()

def _save_priorities(p):
    with open(PRIORITIES_FILE, "w") as f:
        json.dump(p, f)


# ── priority logic ────────────────────────────────────────────────────────
def apply_priorities(payload: dict, score: float, priorities: dict) -> float:
    msg    = (payload.get("message") or "").lower()
    sender = (payload.get("sender")  or "").lower()
    app    = (payload.get("app")     or "other").lower()
    hour   = int((payload.get("context") or {}).get("hour", 12))

    # ── Spam detection (runs before any score adjustments) ───────────────
    if priorities.get("spamEnabled", True):
        spam_result = detect_spam(
            message=payload.get("message", ""),
            sender=payload.get("sender", ""),
            app=app,
            spam_keywords=priorities.get("spamKeywords", []),
        )
        payload["_spam"] = spam_result
        if spam_result["is_spam"]:
            return -1.0   # sentinel: score -1 means spam, skip all further logic

    for vip in priorities.get("vipPersons", []):
        if vip["name"].lower() in sender and vip.get("app", "any") in ("any", app):
            score += 0.35
            break

    kw_hits = sum(1 for kw in priorities.get("keywords", []) if kw.lower() in msg)
    if kw_hits:
        score += 0.12 * min(kw_hits, 3)

    app_w = priorities.get("appWeights", {}).get(app, 50) / 100.0
    score = score * 0.7 + (score * app_w) * 0.3

    if hour in priorities.get("focusHours", []):
        score *= 0.6

    location = (payload.get("context") or {}).get("location", "home")
    activity = (payload.get("context") or {}).get("activity", "idle")
    app_name = (payload.get("app") or "other").lower()

    personal_apps = {"whatsapp", "sms", "phone"}
    is_vip = bool(
        any(
            vip["name"].lower() in (payload.get("sender") or "").lower()
            and vip.get("app", "any") in ("any", app_name)
            for vip in priorities.get("vipPersons", [])
        )
    )
    use_personal_logic = app_name in personal_apps or is_vip

    if use_personal_logic:
        LOCATION_SCORE = {"home": +0.15, "outside": +0.05, "commute": 0.00,
                          "gym": -0.05, "college": -0.08, "office": -0.15}
        ACTIVITY_SCORE = {"idle": +0.12, "scrolling": +0.08, "study": -0.05,
                          "driving": -0.08, "working": -0.12, "sleeping": -0.20}
    else:
        LOCATION_SCORE = {"office": +0.15, "college": +0.10, "commute": +0.05,
                          "home": 0.00, "outside": -0.05, "gym": -0.10}
        ACTIVITY_SCORE = {"working": +0.12, "driving": +0.10, "study": +0.08,
                          "idle": 0.00, "scrolling": -0.08, "sleeping": -0.20}

    score += LOCATION_SCORE.get(location, 0.0)
    score += ACTIVITY_SCORE.get(activity, 0.0)

    rl_ctx = {
        "app":      app_name,
        "location": location,
        "activity": activity,
        "hour":     hour,
        "sender":   (payload.get("sender") or "").lower(),
    }
    score += get_rl_adjustment(rl_ctx)

    return max(0.0, min(1.0, score))


def decide_with_thresholds(score: float, priorities: dict) -> str:
    if score < 0:    return "spam"   # -1.0 sentinel from apply_priorities
    ts = priorities.get("thresholdSend",  70) / 100.0
    td = priorities.get("thresholdDelay", 40) / 100.0
    if score >= ts:  return "send_now"
    if score >= td:  return "delay"
    return "batch"


# ══════════════════════════════════════════════════════════════════════════
#  WEBSOCKET MANAGER  ─  real-time push to all open browser tabs
# ══════════════════════════════════════════════════════════════════════════
class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def count(self):
        return len(self.active)

manager = ConnectionManager()


@app.on_event("startup")
async def startup_event():
    init_scheduler(
        broadcast_fn=manager.broadcast,
        get_focus_hours_fn=lambda: load_priorities().get("focusHours", []),
    )
    asyncio.create_task(start_scheduler_loop())


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Browser connects here to receive real-time notification events.
    Stays alive; server pushes JSON on every /push or /notify call.
    """
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.wait_for(websocket.receive_text(), timeout=30)
    except (WebSocketDisconnect, asyncio.TimeoutError, Exception):
        manager.disconnect(websocket)


# ══════════════════════════════════════════════════════════════════════════
#  /push  ─  Bridge endpoint for REAL device notifications
#
#  Called automatically by:
#    • Android Tasker profile  (HTTP POST on every notification)
#    • iOS Shortcuts automation (runs on every notification)
#    • ADB notification listener script (on the same PC)
#    • Desktop daemons (dunst hook, Windows toast listener)
#
#  Minimal body:
#  {
#    "app":     "whatsapp",
#    "sender":  "Mom",
#    "message": "Call me please",
#    "package": "com.whatsapp",   ← Android package name (optional)
#    "title":   "Mom",            ← notification title  (optional)
#    "context": { "hour":14, "location":"office", "activity":"working" }
#  }
# ══════════════════════════════════════════════════════════════════════════
@app.post("/push")
async def push_notification(notification: dict):
    # Map Android package → friendly name if needed
    pkg = notification.pop("package", None)
    if pkg and not notification.get("app"):
        notification["app"] = _pkg_to_app(pkg)

    # title → sender fallback
    if not notification.get("sender") and notification.get("title"):
        notification["sender"] = notification.pop("title")

    ctx        = notification.pop("context", None)
    priorities = load_priorities()
    result     = run_pipeline([notification], context_overrides=ctx)

    stats = load_stats()
    stats["total"] += 1

    processed = []
    payload_with_ctx = {**notification, "context": ctx or {}}

    for r in result:
        r["score"]  = apply_priorities(payload_with_ctx, r["score"], priorities)
        r["action"] = decide_with_thresholds(r["score"], priorities)
        spam_info   = payload_with_ctx.get("_spam", {})

        stats[r["action"]] = stats.get(r["action"], 0) + 1
        stats["history"].append({
            "app":     notification.get("app", ""),
            "sender":  notification.get("sender", ""),
            "summary": r["summary"],
            "score":   round(max(r["score"], 0), 3),
            "action":  r["action"],
            "context": r.get("context", {}),
            "source":  "device",
            "spam":    spam_info if spam_info.get("is_spam") else None,
        })
        if len(stats["history"]) > 50:
            stats["history"] = stats["history"][-50:]

        # Queue delayed/batched; spam is stored by schedule_notification
        if r["action"] in ("delay", "batch", "spam"):
            schedule_notification(r["action"], r["summary"], payload={
                "app": notification.get("app", ""),
                "sender": notification.get("sender", ""),
                "message": notification.get("message", ""),
            })

        processed.append(r)

    save_stats(stats)

    # Broadcast only non-spam send_now results to browser
    if processed:
        p = processed[0]
        if p["action"] == "spam":
            spam_i = payload_with_ctx.get("_spam", {})
            await manager.broadcast({
                "type":   "spam_blocked",
                "summary": p["summary"],
                "raw": {
                    "app":    notification.get("app", "other"),
                    "sender": notification.get("sender", ""),
                    "message": notification.get("message", ""),
                },
                "spam": spam_i,
                "source": "device",
            })
        else:
            await manager.broadcast({
                "type":   "notification",
                "result": p,
                "raw": {
                    "app":     notification.get("app", "other"),
                    "sender":  notification.get("sender", ""),
                    "message": notification.get("message", ""),
                },
                "source": "device",
            })

    return {"result": processed}


def _pkg_to_app(pkg: str) -> str:
    PKG_MAP = {
        "com.whatsapp":                      "whatsapp",
        "com.whatsapp.w4b":                  "whatsapp",
        "com.google.android.gm":             "gmail",
        "com.slack":                         "slack",
        "org.telegram.messenger":            "telegram",
        "com.instagram.android":             "instagram",
        "com.twitter.android":              "twitter",
        "com.discord":                       "discord",
        "com.google.android.youtube":        "youtube",
        "com.facebook.orca":                 "messenger",
        "com.facebook.katana":               "facebook",
        "com.snapchat.android":              "snapchat",
        "com.microsoft.teams":               "teams",
        "com.linkedin.android":              "linkedin",
        "com.reddit.frontpage":              "reddit",
        "com.google.android.apps.messaging": "sms",
        "com.samsung.android.messaging":     "sms",
        "com.android.mms":                   "sms",
        "com.google.android.dialer":         "phone",
        "com.samsung.android.dialer":        "phone",
    }
    if pkg in PKG_MAP:
        return PKG_MAP[pkg]
    for k, v in PKG_MAP.items():
        if pkg.startswith(k):
            return v
    return pkg.split(".")[-1] if "." in pkg else pkg


@app.get("/ws/status")
def ws_status():
    return {"connected_clients": manager.count}


# ══════════════════════════════════════════════════════════════════════════
#  DEVICE PAIRING  ─  Android companion app endpoints
# ══════════════════════════════════════════════════════════════════════════

# In-memory context updated by the phone
_device_context: dict = {}

def _get_lan_ip() -> str:
    """Discover the machine's LAN IP (not loopback)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@app.get("/device/ip")
def device_ip(request: Request):
    """Return server LAN IP, port, and connection info for the companion app."""
    lan_ip = _get_lan_ip()
    port   = request.url.port or 8000
    return {
        "lan_ip":       lan_ip,
        "port":         port,
        "push_url":     f"http://{lan_ip}:{port}/push",
        "ws_url":       f"ws://{lan_ip}:{port}/ws",
        "app_url":      f"http://{lan_ip}:{port}/android-app/",
        "clients":      manager.count,
        "server_time":  datetime.datetime.now().isoformat(),
    }


@app.get("/device/qr-data")
def device_qr_data(request: Request):
    """JSON used by the companion app's QR code generator."""
    lan_ip = _get_lan_ip()
    port   = request.url.port or 8000
    return {
        "type":     "neuralnotify_pair",
        "push_url": f"http://{lan_ip}:{port}/push",
        "ws_url":   f"ws://{lan_ip}:{port}/ws",
        "version":  "1.0",
    }


@app.get("/device/tasker-xml")
def device_tasker_xml(request: Request):
    """Return a ready-to-import Tasker XML with the correct server IP pre-filled."""
    lan_ip  = _get_lan_ip()
    port    = request.url.port or 8000
    push_url = f"http://{lan_ip}:{port}/push"
    xml = f"""<TaskerData sr="" dvi="1" tv="6.2">
  <Profile sr="prof0" ve="2">
    <cdate>1712000000000</cdate>
    <edate>1712000000000</edate>
    <id>1</id>
    <mid0>1</mid0>
    <nme>NeuralNotify Bridge</nme>
    <Event sr="con0" ve="2">
      <code>9</code>
      <!-- Notification event: fires on EVERY app notification -->
      <Str sr="arg0" ve="3">*</Str>
      <Int sr="arg1" val="0"/>
      <Str sr="arg2" ve="3"/>
    </Event>
  </Profile>

  <Task sr="task1">
    <cdate>1712000000000</cdate>
    <edate>1712000000000</edate>
    <id>1</id>
    <nme>Forward to NeuralNotify</nme>

    <!-- Action 1: HTTP POST to NeuralNotify /push endpoint -->
    <Action sr="act0" ve="7">
      <code>339</code>
      <!-- HTTP Request -->
      <Str sr="arg0" ve="3">POST</Str>
      <!-- Auto-configured server URL -->
      <Str sr="arg1" ve="3">{push_url}</Str>
      <Str sr="arg2" ve="3">Content-Type:application/json</Str>
      <Str sr="arg3" ve="3">{{
  "app": "%entryappname",
  "package": "%entryappname",
  "sender": "%entrytitle",
  "message": "%entrytext",
  "title": "%entrytitle",
  "context": {{
    "hour": %TIMEH,
    "location": "home",
    "activity": "idle"
  }}
}}</Str>
      <Str sr="arg4" ve="3"/>
      <Str sr="arg5" ve="3">application/json</Str>
      <Str sr="arg6" ve="3">result</Str>
      <Int sr="arg7" val="30"/>
      <Int sr="arg8" val="0"/>
    </Action>

  </Task>
</TaskerData>"""
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": "attachment; filename=neuralnotify_tasker.xml"},
    )


@app.post("/device/context")
async def device_context(data: dict):
    """Phone posts its current GPS-derived context here.
    Stored in-memory and used to auto-fill context for the next /push call."""
    global _device_context
    _device_context = {
        "location": data.get("location", "home"),
        "activity": data.get("activity", "idle"),
        "hour":     data.get("hour", datetime.datetime.now().hour),
        "lat":      data.get("lat"),
        "lon":      data.get("lon"),
        "updated":  datetime.datetime.now().isoformat(),
    }
    await manager.broadcast({"type": "context_update", "context": _device_context})
    return {"status": "ok", "context": _device_context}


@app.get("/device/context")
def get_device_context():
    """Return the last context posted by the phone."""
    return _device_context if _device_context else {"status": "no_context_received"}


# ══════════════════════════════════════════════════════════════════════════
#  ALL ORIGINAL ROUTES  ─  every line preserved exactly as shipped
# ══════════════════════════════════════════════════════════════════════════

@app.post("/notify")
async def notify(notification: dict):
    ctx        = notification.pop("context", None)
    priorities = load_priorities()
    result     = run_pipeline([notification], context_overrides=ctx)

    stats = load_stats()
    stats["total"] += 1
    payload_with_ctx = {**notification, "context": ctx or {}}

    for r in result:
        r["score"]  = apply_priorities(payload_with_ctx, r["score"], priorities)
        r["action"] = decide_with_thresholds(r["score"], priorities)
        spam_info   = payload_with_ctx.get("_spam", {})

        stats[r["action"]] = stats.get(r["action"], 0) + 1
        stats["history"].append({
            "app":     notification.get("app", ""),
            "sender":  notification.get("sender", ""),
            "summary": r["summary"],
            "score":   round(max(r["score"], 0), 3),
            "action":  r["action"],
            "context": r.get("context", {}),
            "spam":    spam_info if spam_info.get("is_spam") else None,
        })
        if len(stats["history"]) > 50:
            stats["history"] = stats["history"][-50:]

        if r["action"] in ("delay", "batch", "spam"):
            schedule_notification(r["action"], r["summary"], payload={
                "app": notification.get("app", ""),
                "sender": notification.get("sender", ""),
                "message": notification.get("message", ""),
            })

    save_stats(stats)

    if result:
        p = result[0]
        if p["action"] == "spam":
            spam_i = payload_with_ctx.get("_spam", {})
            await manager.broadcast({
                "type":    "spam_blocked",
                "summary": p["summary"],
                "raw": {
                    "app":     notification.get("app", "other"),
                    "sender":  notification.get("sender", ""),
                    "message": notification.get("message", ""),
                },
                "spam":   spam_i,
                "source": "api",
            })
        else:
            await manager.broadcast({
                "type":   "notification",
                "result": p,
                "raw": {
                    "app":     notification.get("app", "other"),
                    "sender":  notification.get("sender", ""),
                    "message": notification.get("message", ""),
                },
                "source": "api",
            })

    return {"result": result}


@app.post("/feedback")
def feedback(data: dict):
    verdict = data.get("verdict", "correct")
    action  = data.get("action",  "batch")
    score   = float(data.get("score", 0.5))
    ctx     = data.get("context", {})

    rl_result = {}
    if ctx:
        rl_result = rl_record(verdict, action, ctx, score)

    stats = load_stats()
    stats["feedback"].append({
        "verdict": verdict, "action": action,
        "score": score, "ts": data.get("ts"),
        "rl_keys_updated": rl_result.get("weights_updated", []),
    })
    if len(stats["feedback"]) > 200:
        stats["feedback"] = stats["feedback"][-200:]
    save_stats(stats)

    return {"status": "ok", "rl": rl_result}


@app.get("/rl/summary")
def rl_summary():
    return get_rl_summary()


@app.delete("/rl/reset")
def rl_reset():
    return reset_rl()


@app.get("/stats")
def get_stats():
    return load_stats()


@app.delete("/stats/reset")
def reset_stats():
    save_stats({"total": 0, "send_now": 0, "delay": 0, "batch": 0,
                "feedback": [], "history": []})
    return {"status": "reset"}


@app.get("/priorities")
def get_priorities():
    return load_priorities()


@app.post("/priorities")
def save_priorities_endpoint(data: dict):
    current = load_priorities()
    current.update(data)
    _save_priorities(current)
    return {"status": "saved", "priorities": current}


@app.delete("/priorities/reset")
def reset_priorities():
    _save_priorities(DEFAULT_PRIORITIES.copy())
    return {"status": "reset", "priorities": DEFAULT_PRIORITIES}


@app.post("/bundle")
async def bundle(notifications: list):
    ctx_override = None
    if notifications and isinstance(notifications[-1], dict) and "__context__" in notifications[-1]:
        ctx_override = notifications[-1]["__context__"]
        notifications = notifications[:-1]

    if not notifications:
        return {"bundles": []}

    priorities = load_priorities()
    stats = load_stats()

    bundles_raw = bundle_notifications(notifications)
    results = []

    for b in bundles_raw:
        ctx = collect_context(overrides=ctx_override)
        ctx["app_type"] = b["app"].lower()
        ctx["message"]  = b["message"]

        features = encode_context(ctx)
        score    = predict_priority(features)

        payload_for_priorities = {
            "app":     b["app"],
            "sender":  b["sender"],
            "message": b["message"],
            "context": ctx,
        }
        score  = apply_priorities(payload_for_priorities, score, priorities)
        action = decide_with_thresholds(score, priorities)

        stats["total"] += b["count"]
        stats[action]   = stats.get(action, 0) + 1
        stats["history"].append({
            "app":     b["app"],
            "sender":  b["sender"],
            "summary": b["summary"],
            "score":   round(score, 3),
            "action":  action,
            "count":   b["count"],
            "cross_app": b["cross_app"],
            "intent":  b["intent"],
            "context": {
                "hour":     ctx["hour"],
                "location": ctx.get("location", "home"),
                "activity": ctx.get("activity", "idle"),
            },
        })
        if len(stats["history"]) > 50:
            stats["history"] = stats["history"][-50:]

        results.append({
            "summary":   b["summary"],
            "score":     round(score, 3),
            "action":    action,
            "count":     b["count"],
            "cross_app": b["cross_app"],
            "intent":    b["intent"],
            "apps":      b["apps"],
            "sender":    b["sender"],
            "sources":   b["sources"],
            "context": {
                "hour":     ctx["hour"],
                "location": ctx.get("location", "home"),
                "activity": ctx.get("activity", "idle"),
                "app_type": b["app"],
            },
        })

    save_stats(stats)
    return {"bundles": results}


@app.get("/scheduled")
def get_scheduled():
    from app.core.scheduler import get_scheduled_queue
    return {"queue": get_scheduled_queue()}

@app.post("/scheduled/flush")
async def flush_scheduled():
    from app.core.scheduler import flush_scheduled_queue
    count = await flush_scheduled_queue()
    return {"status": "ok", "delivered": count}

@app.get("/spam-log")
def spam_log_endpoint():
    from app.core.scheduler import get_spam_log
    return {"spam_log": get_spam_log()}

@app.delete("/spam-log/clear")
def clear_spam_log():
    import json, os
    path = "data/logs/spam_log.json"
    with open(path, "w") as f:
        json.dump([], f)
    return {"status": "cleared"}

@app.post("/retrain")
def retrain_model():
    return retrain()


app.include_router(routes_dataset.router)

# Android companion PWA — served at /android-app/ (must come before the "/" catch-all)
os.makedirs("android-app", exist_ok=True)
app.mount("/android-app", StaticFiles(directory="android-app", html=True), name="android-app")

# Static files must be mounted LAST so API routes take priority
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
