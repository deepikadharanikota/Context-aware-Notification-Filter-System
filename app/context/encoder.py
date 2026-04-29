LOCATION_MAP = {
    "home": 0, "office": 1, "college": 2,
    "commute": 3, "gym": 4, "outside": 5
}

ACTIVITY_MAP = {
    "idle": 0, "study": 1, "working": 2,
    "scrolling": 3, "sleeping": 4, "driving": 5
}

APP_TYPE_MAP = {
    "whatsapp": 0, "gmail": 1, "slack": 2,
    "instagram": 3, "twitter": 4, "youtube": 5,
    "sms": 6, "phone": 7, "other": 8
}

URGENT_KEYWORDS = [
    "urgent", "asap", "immediately", "emergency", "deadline",
    "critical", "important", "help", "now", "alert", "warning", "fail"
]

def encode_context(ctx):
    """
    Encode a context+notification dict into 12 features for the model.
    """
    hour = int(ctx.get("hour", 12))
    day_of_week = int(ctx.get("day_of_week", 0))
    is_weekend = int(ctx.get("is_weekend", 0))
    location = LOCATION_MAP.get(ctx.get("location", "home"), 0)
    activity = ACTIVITY_MAP.get(ctx.get("activity", "idle"), 0)
    app_type = APP_TYPE_MAP.get(ctx.get("app_type", "other"), 8)

    message = str(ctx.get("message", "")).lower()
    urgency_score = sum(1 for kw in URGENT_KEYWORDS if kw in message)
    message_length = min(len(message), 500)
    has_question = 1 if "?" in message else 0
    has_exclaim = 1 if "!" in message else 0
    is_night = 1 if (hour >= 22 or hour < 6) else 0
    is_work_hours = 1 if (9 <= hour < 18 and not is_weekend) else 0

    return [
        hour, day_of_week, is_weekend,
        location, activity, app_type,
        urgency_score, message_length,
        has_question, has_exclaim,
        is_night, is_work_hours
    ]
