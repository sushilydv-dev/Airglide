"""Picks the parts of a presentation that matter for a question.

A small on-device model has a limited context window, so instead of sending
the whole deck we send: a compact outline (all slide titles), the current
slide, and the slides that best match the question (BM25 ranking).
"""
import math
import re

STOPWORDS = set("""
a an the and or but if then than so of to in on at by for with about from into over under
is are was were be been being am do does did done have has had having it its it's this that
these those there here what which who whom whose when where why how i me my we our you your
he she they them their his her can could should would will shall may might must not no yes
please tell show give get make let just also very more most some any all each every much many
one two three slide slides deck presentation talk page pages section sections
""".split())

# Requests that are about the deck even when they share no words with it.
DECK_WORDS = re.compile(
    r"\b(slide|slides|deck|presentation|talk|speech|present|presenting|audience|summar\w*|"
    r"overview|outline|key (points|takeaways)|takeaway\w*|talking points?|"
    r"main points?|section|document|intro\w*|conclu\w*)\b", re.I)

# "this slide", "current page", "the slide I'm on"... -> focus on the current one only.
CURRENT_REF = re.compile(r"\b(current|this|present)\s+(slide|page|section)\b|\bslide i'?m on\b", re.I)

WORD = re.compile(r"[a-z0-9][a-z0-9'%$.-]*", re.I)


def tokens(text):
    out = []
    for w in WORD.findall((text or "").lower()):
        w = w.strip(".'-")
        if len(w) > 1 and w not in STOPWORDS:
            out.append(_stem(w))
    return out


def _stem(w):
    for suffix in ("ing", "ies", "es", "ed", "s"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return w


def bm25_scores(query, docs, k1=1.4, b=0.75):
    q = tokens(query)
    doc_tokens = [tokens(d) for d in docs]
    n = len(docs)
    if not n or not q:
        return [0.0] * n
    avg = sum(len(t) for t in doc_tokens) / n or 1
    df = {}
    for t in doc_tokens:
        for w in set(t):
            df[w] = df.get(w, 0) + 1
    scores = []
    for t in doc_tokens:
        tf = {}
        for w in t:
            tf[w] = tf.get(w, 0) + 1
        s = 0.0
        for w in set(q):
            if w not in tf:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(t) / avg))
        scores.append(s)
    return scores


def is_relevant(question, slides):
    """False only for questions that clearly have nothing to do with the deck."""
    if DECK_WORDS.search(question or ""):
        return True
    q = set(tokens(question))
    if not q:
        return True   # too short to judge; let the model handle it
    vocab = set()
    for s in slides:
        vocab.update(tokens(s.get("text", "")))
        vocab.update(tokens(s.get("title", "")))
    return bool(q & vocab)


def _slide_text(s, limit):
    text = re.sub(r"\n{2,}", "\n", s.get("text", "")).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def build_context(question, slides, current=None, budget_chars=7000, unit="Slide", outline=True):
    """Text block with (optionally) an outline plus the most useful slides for `question`."""
    if not slides:
        return "(No presentation text is available.)"
    parts = []
    if outline:
        lines = "\n".join(f"{s['slide_number']}. {s.get('title') or '(untitled)'}" for s in slides[:80])
        if len(slides) > 80:
            lines += f"\n… and {len(slides) - 80} more"
        parts.append(f"Outline:\n{lines}")
    used = sum(len(p) for p in parts)

    scores = bm25_scores(question, [f"{s.get('title', '')}\n{s.get('text', '')}" for s in slides])
    order = sorted(range(len(slides)), key=lambda i: scores[i], reverse=True)
    chosen = []
    if current and 1 <= current <= len(slides):
        chosen.append(current - 1)
        if CURRENT_REF.search(question or ""):
            block = f"[{unit} {slides[current - 1]['slide_number']}] {_slide_text(slides[current - 1], budget_chars)}"
            parts.append(f"Current {unit.lower()} (answer about this one only):\n{block}")
            return "\n\n".join(parts)
    chosen += [i for i in order if scores[i] > 0 and i not in chosen]
    # Nothing matched (e.g. "summarise the deck"): walk the deck in order.
    if len(chosen) <= (1 if current else 0):
        chosen += [i for i in range(len(slides)) if i not in chosen]

    picked = []
    per_slide = max(400, budget_chars // 6)
    for i in chosen:
        block = f"[{unit} {slides[i]['slide_number']}] {_slide_text(slides[i], per_slide)}"
        if used + len(block) > budget_chars and picked:
            break
        picked.append((slides[i]["slide_number"], block))
        used += len(block)
    picked.sort()
    parts.append(f"{unit} content:\n" + "\n\n".join(b for _, b in picked))
    return "\n\n".join(parts)
