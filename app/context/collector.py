import datetime

def collect_context(overrides=None):
    """
    Collect real context. Overrides dict allows frontend to inject values.
    """
    now = datetime.datetime.now()
    hour = now.hour
    day_of_week = now.weekday()  # 0=Mon, 6=Sun
    is_weekend = 1 if day_of_week >= 5 else 0

    ctx = {
        "hour": hour,
        "day_of_week": day_of_week,
        "is_weekend": is_weekend,
        "location": "home",
        "activity": "idle",
    }

    if overrides:
        ctx.update(overrides)

    return ctx
