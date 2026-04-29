def decide_action(score: float,
                  threshold_send: float = 0.7,
                  threshold_delay: float = 0.4) -> str:
    """
    Convert a priority score into an action label.

    Thresholds are configurable so the pipeline can use different cutoffs
    when user preferences are available.  The defaults reproduce the original
    0.7 / 0.4 behaviour so existing callers are unaffected.
    """
    if score >= threshold_send:
        return "send_now"
    elif score >= threshold_delay:
        return "delay"
    return "batch"
