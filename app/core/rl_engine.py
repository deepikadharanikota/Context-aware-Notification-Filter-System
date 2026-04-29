"""
rl_engine.py — Lightweight Reinforcement Learning layer for NeuralNotify.

HOW IT WORKS
------------
Every time the user gives feedback (👍 correct / 👎 wrong) the system logs
the full context of that notification and updates a small set of "adjustment
weights" stored in data/logs/rl_weights.json.

The weights are deltas (+/-) applied on top of the regular scoring pipeline.
They are keyed by context dimensions that matter:

    app          → which app sent the notification
    location     → where the user was
    activity     → what the user was doing
    hour_bucket  → time-of-day band (night/morning/work/evening)

On every new notification these deltas are summed and added to the score
AFTER all other modifiers, so the RL layer never replaces existing logic —
it only nudges the final number up or down based on observed user preferences.

LEARNING RULE  (simple policy-gradient style)
------------
• 👍 correct  → the decision was right. Reinforce the context: push weights
                 in the direction of the current decision.
• 👎 wrong    → the decision was wrong. The user wanted the opposite action.
                 Push weights away from the current decision.

Step size (alpha) is small (0.03) so a single data point doesn't dominate,
and weights are clamped to [-0.4, +0.4] to stay bounded.

PERSISTENCE
-----------
Weights live in data/logs/rl_weights.json and survive restarts.
The file is human-readable so users/devs can inspect or reset it.
"""

import json
import os
from typing import Any

RL_WEIGHTS_FILE = "data/logs/rl_weights.json"
RL_LOG_FILE     = "data/logs/rl_feedback_log.json"

# Learning rate — how much each feedback shifts the weight
ALPHA = 0.03

# Maximum absolute value any single weight can reach
WEIGHT_CLAMP = 0.40

# How many raw feedback entries to keep in the log
MAX_LOG_ENTRIES = 500

# Hour → named bucket
def _hour_bucket(hour: int) -> str:
    if 22 <= hour or hour < 6:   return "night"
    if 6  <= hour < 9:           return "morning"
    if 9  <= hour < 18:          return "work_hours"
    return "evening"


def _load_weights() -> dict:
    if os.path.exists(RL_WEIGHTS_FILE):
        try:
            with open(RL_WEIGHTS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_weights(w: dict) -> None:
    os.makedirs(os.path.dirname(RL_WEIGHTS_FILE), exist_ok=True)
    with open(RL_WEIGHTS_FILE, "w") as f:
        json.dump(w, f, indent=2)


def _load_log() -> list:
    if os.path.exists(RL_LOG_FILE):
        try:
            with open(RL_LOG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_log(log: list) -> None:
    os.makedirs(os.path.dirname(RL_LOG_FILE), exist_ok=True)
    with open(RL_LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


def _context_keys(ctx: dict) -> list[str]:
    """
    Return the list of weight keys that describe this notification context.
    Each key is a string like  "app:whatsapp"  or  "location:office".
    """
    keys = []
    if ctx.get("app"):
        keys.append(f"app:{ctx['app'].lower()}")
    if ctx.get("location"):
        keys.append(f"location:{ctx['location'].lower()}")
    if ctx.get("activity"):
        keys.append(f"activity:{ctx['activity'].lower()}")
    hour = ctx.get("hour")
    if hour is not None:
        keys.append(f"hour_bucket:{_hour_bucket(int(hour))}")
    # Combined key for fine-grained patterns (app + activity)
    if ctx.get("app") and ctx.get("activity"):
        keys.append(f"app:{ctx['app'].lower()}+activity:{ctx['activity'].lower()}")
    return keys


def get_rl_adjustment(ctx: dict) -> float:
    """
    Return the total RL score adjustment for a given context dict.
    Called by the scoring pipeline AFTER all other modifiers.
    ctx should contain: app, location, activity, hour (and optionally sender).
    """
    weights = _load_weights()
    if not weights:
        return 0.0
    total = sum(weights.get(k, 0.0) for k in _context_keys(ctx))
    # Clamp total adjustment to [-0.5, +0.5]
    return max(-0.50, min(0.50, total))


def record_feedback(verdict: str, action: str, ctx: dict, score: float) -> dict:
    """
    Process one piece of user feedback and update the RL weights.

    Parameters
    ----------
    verdict : "correct" or "wrong"
    action  : the action that was shown ("send_now" / "delay" / "batch")
    ctx     : full context dict (app, location, activity, hour, sender, ...)
    score   : the score that produced this action (0-1)

    Returns
    -------
    dict with keys: weights_updated (list), adjustment (float)
    """
    weights = _load_weights()

    # Direction: +1 means "score should be higher", -1 means "lower"
    # correct  → current decision was right → reinforce current score direction
    # wrong    → current decision was wrong → push opposite direction
    if verdict == "correct":
        # Reinforce: send_now → push up, batch → push down, delay → neutral
        direction = {"send_now": +1, "delay": 0, "batch": -1}.get(action, 0)
    else:  # wrong
        # Invert: if we said send_now but user disagreed → push down
        direction = {"send_now": -1, "delay": 0, "batch": +1}.get(action, 0)

    if direction == 0:
        # "delay" feedback is ambiguous — still log it but don't shift weights
        updated_keys = []
    else:
        keys = _context_keys(ctx)
        for k in keys:
            current = weights.get(k, 0.0)
            updated = current + ALPHA * direction
            weights[k] = max(-WEIGHT_CLAMP, min(WEIGHT_CLAMP, updated))
        updated_keys = keys
        _save_weights(weights)

    # Append to human-readable feedback log
    log = _load_log()
    log.append({
        "verdict":  verdict,
        "action":   action,
        "score":    round(score, 3),
        "ctx":      ctx,
        "keys":     updated_keys,
        "direction": direction,
    })
    if len(log) > MAX_LOG_ENTRIES:
        log = log[-MAX_LOG_ENTRIES:]
    _save_log(log)

    return {
        "weights_updated": updated_keys,
        "adjustment":      get_rl_adjustment(ctx),
        "direction":       direction,
    }


def get_rl_summary() -> dict:
    """Return a human-readable summary of what the RL layer has learned."""
    weights = _load_weights()
    log     = _load_log()

    # Top boosted and suppressed contexts
    sorted_w = sorted(weights.items(), key=lambda x: x[1])
    suppressed = [{"key": k, "weight": round(v, 3)} for k, v in sorted_w[:5]  if v < 0]
    boosted    = [{"key": k, "weight": round(v, 3)} for k, v in sorted_w[-5:] if v > 0]

    return {
        "total_feedback_entries": len(log),
        "total_weight_keys":      len(weights),
        "most_boosted":           list(reversed(boosted)),
        "most_suppressed":        suppressed,
        "raw_weights":            weights,
    }


def reset_rl() -> dict:
    """Wipe all learned weights (keeps the log)."""
    _save_weights({})
    return {"status": "rl_weights_reset"}
