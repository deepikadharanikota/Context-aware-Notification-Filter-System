from collections import defaultdict

# Lazy-loaded — NOT imported/downloaded at startup.
# Model is only fetched the first time summarize_notifications() is actually called
# with a multi-message group that needs real summarisation.
_summarizer_model = None
_summarizer_tried = False   # don't retry after a failed load


def _get_summarizer():
    global _summarizer_model, _summarizer_tried
    if _summarizer_tried:
        return _summarizer_model
    _summarizer_tried = True
    try:
        from transformers import pipeline as hf_pipeline
        _summarizer_model = hf_pipeline("summarization", model="t5-small")
    except Exception:
        _summarizer_model = None
    return _summarizer_model


def summarize_notifications(notifications):
    grouped = defaultdict(list)
    for n in notifications:
        grouped[n.get("app","General")].append(n)

    summaries = []
    for app, items in grouped.items():
        if len(items)==1:
            summaries.append(items[0]["message"])
        else:
            text = " ".join([f"{i.get('sender','Unknown')} says {i['message']}" for i in items])
            summarizer_model = _get_summarizer()
            if summarizer_model:
                try:
                    s = summarizer_model(text, max_length=50, min_length=10)[0]['summary_text']
                except:
                    s = text[:100]
            else:
                s = text[:100]
            summaries.append(f"{len(items)} msgs from {app}: {s}")
    return summaries