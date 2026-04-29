from app.context.collector import collect_context
from app.context.encoder import encode_context
from app.models.priority_model import predict_priority
from app.core.decision_engine import decide_action
from app.core.scheduler import schedule_notification
from app.models.summarizer import summarize_notifications
from app.models.spam_filter import is_spam   # ✅ ADD THIS


def run_pipeline(notifications, context_overrides=None):
    summaries = summarize_notifications(notifications)
    results = []

    for i, summary in enumerate(summaries):

        notif = notifications[i] if i < len(notifications) else {}

        # 🔹 Extract message early
        message_text = notif.get("message", notif.get("body", summary))

        # ✅ STEP 1: SPAM CHECK (VERY IMPORTANT)
        if is_spam(message_text):
            results.append({
                "summary": summary,
                "score": 0,
                "action": "SUPPRESS",
                "context": {"reason": "spam detected"}
            })
            continue   # ❗ skip rest of pipeline

        # 🔹 Continue normal flow
        ctx = collect_context(overrides=context_overrides)
        ctx["app_type"] = notif.get("app", "other").lower()
        ctx["message"] = message_text

        features = encode_context(ctx)
        score = predict_priority(features)
        action = decide_action(score)

        full_payload = {
            "app":     notif.get("app", "other"),
            "sender":  notif.get("sender", ""),
            "message": message_text,
        }

        schedule_notification(action, summary, payload=full_payload)

        results.append({
            "summary": summary,
            "score": score,
            "action": action,
            "context": {
                "hour": ctx["hour"],
                "location": ctx.get("location", "home"),
                "activity": ctx.get("activity", "idle"),
                "app_type": ctx["app_type"],
            }
        })

    return results