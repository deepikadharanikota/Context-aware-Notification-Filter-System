"""
smart_bundler.py — Semantic notification bundling with BERT embeddings.

FLOW
----
1.  Receive a list of raw notifications (each has app, sender, message, context).
2.  Embed every message with BERT (sentence-transformers/paraphrase-MiniLM-L6-v2).
    Falls back to TF-IDF cosine similarity if sentence-transformers is not installed.
3.  Group notifications that share the same sender OR are semantically similar
    (cosine similarity > SIMILARITY_THRESHOLD) within a short time window.
4.  For each group, produce one smart summary using extractive + template logic:
      - Detect the intent (call request, question, greeting, info, urgent)
      - Pick the most informative sentence
      - Format as:  "<Sender> wants you to <intent>  •  <app> · <N> messages"
5.  Return each bundle as a dict that the pipeline / API can handle normally.

BERT MODEL
----------
Uses  paraphrase-MiniLM-L6-v2  (22 MB, fast, good for short texts like notifs).
Downloaded once to ~/.cache/torch/sentence_transformers on first run.
If unavailable, TF-IDF is used — still groups by keyword overlap + sender match.
"""

import re
import math
import logging
from collections import defaultdict
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# ── Similarity threshold for grouping ────────────────────────────────────────
SIMILARITY_THRESHOLD = 0.45   # 0-1; higher = stricter grouping

# ── Try loading BERT encoder ──────────────────────────────────────────────────
_bert_model = None

def _load_bert():
    global _bert_model
    if _bert_model is not None:
        return _bert_model
    try:
        from sentence_transformers import SentenceTransformer
        _bert_model = SentenceTransformer("paraphrase-MiniLM-L6-v2")
        logger.info("smart_bundler: BERT model loaded (paraphrase-MiniLM-L6-v2)")
    except Exception as e:
        logger.warning(f"smart_bundler: sentence-transformers unavailable ({e}), using TF-IDF fallback")
        _bert_model = None
    return _bert_model


# ── Embedding helpers ─────────────────────────────────────────────────────────

def _bert_embed(texts: List[str]):
    """Return numpy array of shape (N, D) using BERT."""
    model = _load_bert()
    if model is None:
        return None
    return model.encode(texts, convert_to_numpy=True, show_progress_bar=False)


def _tfidf_embed(texts: List[str]):
    """TF-IDF fallback — returns (N, V) sparse-like matrix via sklearn."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, stop_words="english")
    try:
        mat = vec.fit_transform(texts)
        return mat.toarray()
    except Exception:
        return None


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _embed_all(texts: List[str]):
    """Try BERT first, fall back to TF-IDF."""
    emb = _bert_embed(texts)
    if emb is None:
        emb = _tfidf_embed(texts)
    return emb   # None if both fail


# ── Intent detection ──────────────────────────────────────────────────────────

INTENT_PATTERNS = [
    ("call_back",  r"\bcall\b|\bring\b|\bphone\b|\bcalling\b"),
    ("urgent",     r"\burgent\b|\basap\b|\bimmediately\b|\bemergency\b|\bcritical\b|\bhelp\b"),
    ("question",   r"\?"),
    ("meeting",    r"\bmeeting\b|\bschedule\b|\bappointment\b|\bjoin\b|\bzoom\b|\bmeet\b"),
    ("location",   r"\bwhere\b|\bcome\b|\bhere\b|\bthere\b|\baddress\b|\blocation\b"),
    ("greeting",   r"\bhello\b|\bhi\b|\bhey\b|\bgood morning\b|\bgood evening\b|\bgood night\b"),
    ("info",       r".*"),    # catch-all
]

def _detect_intent(messages: List[str]) -> str:
    """Return the dominant intent label across all messages in a group."""
    combined = " ".join(messages).lower()
    for intent, pattern in INTENT_PATTERNS:
        if re.search(pattern, combined):
            return intent
    return "info"


INTENT_PHRASES = {
    "call_back": "wants you to call back",
    "urgent":    "sent an urgent message",
    "question":  "is asking you something",
    "meeting":   "mentioned a meeting",
    "location":  "shared a location / directions",
    "greeting":  "sent you a greeting",
    "info":      "sent you a message",
}


# ── Key sentence extractor ────────────────────────────────────────────────────

def _key_sentence(messages: List[str]) -> str:
    """
    Pick the single most informative sentence across all messages.
    Ranks by: contains '?' or '!' > contains intent keywords > longest.
    """
    sentences = []
    for msg in messages:
        for s in re.split(r'[.!?\n]+', msg):
            s = s.strip()
            if s:
                sentences.append(s)
    if not sentences:
        return ""
    # Score each sentence
    def score(s):
        sl = s.lower()
        pts = 0
        if '?' in s: pts += 3
        if '!' in s: pts += 2
        for intent, pat in INTENT_PATTERNS[:-1]:   # skip catch-all
            if re.search(pat, sl): pts += 2
        pts += min(len(s) / 20, 3)   # length bonus, capped
        return pts
    return max(sentences, key=score)


# ── Core grouping logic ───────────────────────────────────────────────────────

def _group_notifications(notifications: List[Dict[str, Any]]) -> List[List[int]]:
    """
    Return a list of groups (each group = list of original indices).

    Grouping rules (applied in order):
    1. Same sender + same app  →  always merge.
    2. Same sender, different app (cross-app)  →  merge if semantically similar.
    3. Different sender  →  only merge if BERT similarity > threshold AND same app.
    """
    n = len(notifications)
    if n == 0:
        return []
    if n == 1:
        return [[0]]

    texts = [notif.get("message", "") or "" for notif in notifications]

    # Embed all messages
    embeddings = _embed_all(texts) if n > 1 else None

    # Union-Find for grouping
    parent = list(range(n))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(x, y):
        parent[find(x)] = find(y)

    for i in range(n):
        for j in range(i + 1, n):
            ni = notifications[i]
            nj = notifications[j]
            si = (ni.get("sender") or "").strip().lower()
            sj = (nj.get("sender") or "").strip().lower()
            ai = (ni.get("app") or "").lower()
            aj = (nj.get("app") or "").lower()

            same_sender = si and sj and si == sj
            same_app    = ai == aj

            # Rule 1: same sender + same app → always merge
            if same_sender and same_app:
                union(i, j)
                continue

            # Compute semantic similarity if embeddings available
            sim = 0.0
            if embeddings is not None:
                try:
                    sim = float(_cosine(embeddings[i].tolist(), embeddings[j].tolist()))
                except Exception:
                    sim = 0.0

            # Rule 2: same sender, cross-app → merge if semantically related
            if same_sender and not same_app:
                if sim >= SIMILARITY_THRESHOLD:
                    union(i, j)
                continue

            # Rule 3: different sender, same app → merge only if very similar
            if not same_sender and same_app:
                if sim >= SIMILARITY_THRESHOLD + 0.15:   # stricter
                    union(i, j)

    # Collect groups
    group_map: Dict[int, List[int]] = defaultdict(list)
    for i in range(n):
        group_map[find(i)].append(i)
    return list(group_map.values())


# ── Public API ────────────────────────────────────────────────────────────────

def bundle_notifications(notifications: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Main entry point.  Takes a list of raw notification dicts, returns a list
    of bundle dicts — one per group — ready to be fed into the pipeline.

    Each bundle dict:
    {
        "app":         str,             # primary app (most common in group)
        "sender":      str,             # primary sender
        "message":     str,             # combined raw text (for scoring)
        "summary":     str,             # human-readable smart summary
        "sources":     List[dict],      # original notifications in this bundle
        "count":       int,             # how many notifications were merged
        "cross_app":   bool,            # True if messages came from >1 app
        "intent":      str,             # detected intent label
    }
    """
    if not notifications:
        return []

    groups = _group_notifications(notifications)
    bundles = []

    for group_indices in groups:
        group_notifs = [notifications[i] for i in group_indices]

        messages = [n.get("message", "") or "" for n in group_notifs]
        senders  = [n.get("sender",  "") or "" for n in group_notifs]
        apps     = [n.get("app",     "") or "" for n in group_notifs]

        # Primary sender = most common non-empty sender
        sender_counts = defaultdict(int)
        for s in senders:
            if s.strip():
                sender_counts[s.strip()] += 1
        primary_sender = max(sender_counts, key=sender_counts.get) if sender_counts else "Unknown"

        # Primary app = most common
        app_counts = defaultdict(int)
        for a in apps:
            if a.strip():
                app_counts[a.strip()] += 1
        primary_app = max(app_counts, key=app_counts.get) if app_counts else "other"

        unique_apps = list(dict.fromkeys(a for a in apps if a))
        cross_app   = len(unique_apps) > 1

        # Detect intent
        intent      = _detect_intent(messages)
        intent_phrase = INTENT_PHRASES.get(intent, "sent you a message")

        # Key sentence for the summary detail
        key_sent = _key_sentence(messages)

        # Build the smart summary
        count = len(group_notifs)
        if count == 1:
            smart_summary = messages[0][:140] if messages[0] else "(no message)"
        else:
            app_label = " & ".join(unique_apps) if cross_app else primary_app
            base = f"{primary_sender} {intent_phrase}"
            detail = f'"{key_sent}"' if key_sent and key_sent.lower() not in base.lower() else ""
            meta   = f"{app_label} · {count} message{'s' if count > 1 else ''}"
            parts  = [base]
            if detail:
                parts.append(detail)
            parts.append(f"[{meta}]")
            smart_summary = "  •  ".join(parts)

        # Combined raw message for ML scoring (join all messages)
        combined_message = " ".join(m for m in messages if m)

        bundles.append({
            "app":     primary_app,
            "sender":  primary_sender,
            "message": combined_message,
            "summary": smart_summary,
            "sources": group_notifs,
            "count":   count,
            "cross_app": cross_app,
            "intent":  intent,
            "apps":    unique_apps,
        })

    return bundles
