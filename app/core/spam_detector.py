"""
spam_detector.py
────────────────
Detects promotional/spam notifications that contain high-priority-sounding
keywords but are actually unsolicited marketing content.

Strategy:
  1. Check sender/app against known spam sources (promo senders, marketing apps).
  2. Score the message against spam keyword patterns.
  3. If spam_score crosses SPAM_THRESHOLD → mark as spam and block delivery.

The spam keyword list is separate from the user's priority keywords so that
words like "urgent" can be both a priority booster AND a spam trigger
depending on context (sender + app).
"""

import re

# ── Default spam keyword groups ──────────────────────────────────────────
DEFAULT_SPAM_KEYWORDS: list[str] = [
    # Sale / discount bait
    "sale", "offer", "discount", "cashback", "deal", "coupon", "promo",
    "promocode", "voucher", "flat off", "% off", "buy now", "limited offer",
    "exclusive offer", "flash sale", "mega sale", "season sale", "big sale",
    "best price", "lowest price", "price drop", "clearance",

    # Lottery / prize scams
    "lottery", "winner", "won", "winning", "prize", "reward", "jackpot",
    "lucky draw", "congratulations you", "claim your", "you have been selected",
    "selected for", "free gift", "free iphone", "free trip",

    # Loan / financial spam
    "gold loan", "personal loan", "loan approved", "pre-approved loan",
    "instant loan", "easy loan", "quick loan", "loan offer",
    "credit card offer", "credit limit increase", "emi offer",
    "apply now", "zero interest", "0% interest",

    # Urgency bait (used in spam, not genuine urgent messages)
    "act now", "don't miss", "dont miss", "hurry", "last chance",
    "expires today", "expiring soon", "valid today", "today only",
    "limited time", "grab now",

    # Travel spam
    "trip offer", "holiday offer", "tour package", "travel deal",
    "book now", "flight offer", "hotel offer", "resort offer",
    "vacation deal",

    # Generic marketing
    "click here", "visit now", "download now", "install now",
    "subscribe now", "sign up now", "register now",
    "earn money", "work from home", "passive income",
    "investment opportunity", "guaranteed returns",
]

# ── Apps that almost never send spam ─────────────────────────────────────
TRUSTED_APPS = {
    "phone", "sms", "whatsapp", "slack", "teams",
    "telegram", "signal", "facetime",
}

# ── Apps that frequently send promotional content ─────────────────────────
PROMO_APPS = {
    "gmail", "email", "instagram", "facebook", "twitter",
    "youtube", "snapchat", "reddit", "linkedin",
    "flipkart", "amazon", "myntra", "meesho", "ajio",
    "swiggy", "zomato", "phonepe", "paytm", "googlepay",
}

# Minimum spam keyword hits to flag as spam
SPAM_THRESHOLD = 2


def detect_spam(
    message: str,
    sender: str = "",
    app: str = "",
    spam_keywords: list[str] | None = None,
) -> dict:
    """
    Returns a dict:
      {
        "is_spam": bool,
        "spam_score": int,          # number of spam signals matched
        "matched_keywords": list,   # which spam keywords were found
        "reason": str               # human-readable reason
      }
    """
    if spam_keywords is None:
        spam_keywords = DEFAULT_SPAM_KEYWORDS

    msg    = message.lower()
    sender = sender.lower()
    app    = app.lower()

    # Trusted apps — never spam regardless of content
    if app in TRUSTED_APPS:
        return _clean(spam_score=0, matched=[])

    matched: list[str] = []
    spam_score = 0

    # ── 1. Keyword scan ──────────────────────────────────────────────────
    all_keywords = list(set(DEFAULT_SPAM_KEYWORDS + (spam_keywords or [])))
    for kw in all_keywords:
        # Use word-boundary matching for short keywords (≤4 chars) to avoid
        # matching "loan" inside "balloon" etc.
        if len(kw) <= 4:
            pattern = r'\b' + re.escape(kw) + r'\b'
        else:
            pattern = re.escape(kw)
        if re.search(pattern, msg):
            matched.append(kw)
            spam_score += 1

    # ── 2. Promo app boost ───────────────────────────────────────────────
    if app in PROMO_APPS and spam_score >= 1:
        spam_score += 1  # promo apps get extra suspicion

    # ── 3. Suspicious sender patterns ───────────────────────────────────
    spam_sender_patterns = [
        r'\bnoreply\b', r'\bno.reply\b', r'\bmarketing\b', r'\bpromo\b',
        r'\boffers?\b', r'\bnewsletter\b', r'\bdeals?\b', r'\balerts?\b',
        r'\bnotification\b', r'\bsupport@\b', r'\binfo@\b',
    ]
    for pat in spam_sender_patterns:
        if re.search(pat, sender):
            spam_score += 1
            break  # count sender as one signal

    is_spam = spam_score >= SPAM_THRESHOLD

    reason = ""
    if is_spam:
        reason = f"Matched {len(matched)} spam keyword(s): {', '.join(matched[:5])}"
        if app in PROMO_APPS:
            reason += f" (promotional app: {app})"

    return {
        "is_spam":          is_spam,
        "spam_score":       spam_score,
        "matched_keywords": matched,
        "reason":           reason,
    }


def _clean(spam_score: int, matched: list) -> dict:
    return {
        "is_spam":          False,
        "spam_score":       spam_score,
        "matched_keywords": matched,
        "reason":           "",
    }
