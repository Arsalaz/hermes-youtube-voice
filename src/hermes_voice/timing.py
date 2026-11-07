from __future__ import annotations
import re

_VOWELS = set("aeıioöuüAEIİOÖUÜ")
_PUNCT_TAIL = re.compile(r"([,;:—–]|[.!?…]+)[\"”’')\]]*$")


def _weight(word: str) -> float:
    letters = [c for c in word if c.isalpha()]
    v = sum(1 for c in letters if c in _VOWELS)
    c = len(letters) - v
    if not letters:                       # sayı veya sembol: uzunlukla orantılı
        return max(1.0, len(word) * 1.2)
    w = 2.0 * v + 0.7 * c + 0.5
    if m := _PUNCT_TAIL.search(word):
        w += 4.0 if m.group(1)[-1] in ".!?…" else 2.5
    return w


def estimate_words(text: str, start: float, end: float) -> list[dict]:
    words = text.split()
    if not words or end <= start:
        return []
    ws = [_weight(w) for w in words]
    total = sum(ws)
    dur = end - start
    out, t = [], start
    for w, wt in zip(words, ws):
        d = dur * wt / total
        out.append({"w": w, "s": round(t, 3), "e": round(t + d, 3)})
        t += d
    out[-1]["e"] = round(end, 3)
    return out
