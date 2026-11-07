from __future__ import annotations
import re
from dataclasses import dataclass

from .config import Config
from .markup import Block, parse

ABBR = {
    "dr", "prof", "doç", "yrd", "sn", "sayın", "bkz", "vb", "vs", "yy", "örn",
    "no", "st", "mah", "cad", "sok", "tel", "kg", "km", "cm", "mm", "tl", "a.ş", "ltd", "şti",
}
_END = re.compile(r"([.!?…]+)[\"”’')\]]*$")
_CLAUSE = re.compile(r"(?<=[,;:—–])\s+")
_OPEN_OK = re.compile(r"^[\"“‘(\[]*[A-ZÇĞİÖŞÜ0-9]")


@dataclass
class Segment:
    idx: int
    text: str
    pause_after: float
    scene: str


def _is_sentence_end(word: str, nxt: str | None) -> bool:
    m = _END.search(word)
    if not m:
        return False
    core = word[: m.start()].lower().strip("\"“‘(['")
    if core in ABBR or (core.isdigit() and m.group(1) == "."):
        # "Dr." veya "3." yalnızca sonraki sözcük küçük harfliyse cümle içidir
        if nxt is not None and not nxt[:1].isupper():
            return False
        if core in ABBR:
            return False
    return nxt is None or bool(_OPEN_OK.match(nxt))


def split_sentences(text: str) -> list[str]:
    words = text.split()
    out: list[str] = []
    cur: list[str] = []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if _is_sentence_end(w, nxt):
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out


def _hard_split(s: str, limit: int) -> list[str]:
    parts, cur = [], ""
    for w in s.split():
        if cur and len(cur) + 1 + len(w) > limit:
            parts.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        parts.append(cur)
    return parts


def split_long(sentence: str, limit: int) -> list[str]:
    if len(sentence) <= limit:
        return [sentence]
    packed, cur = [], ""
    for piece in _CLAUSE.split(sentence):
        if cur and len(cur) + 1 + len(piece) > limit:
            packed.append(cur)
            cur = piece
        else:
            cur = f"{cur} {piece}".strip()
    if cur:
        packed.append(cur)
    final: list[str] = []
    for p in packed:
        final.extend(_hard_split(p, limit) if len(p) > limit else [p])
    return final


def _terminal_pause(text: str, cfg: Config) -> float:
    m = _END.search(text.strip())
    if not m:
        return cfg.pause_clause
    t = m.group(1)
    if "…" in t or t.startswith(".."):
        return cfg.pause_ellipsis
    return {"?": cfg.pause_question, "!": cfg.pause_exclaim}.get(t[-1], cfg.pause_period)


def segment(script: str, cfg: Config) -> list[Segment]:
    segs: list[Segment] = []
    scene = "s0"

    def add(text: str, pause: float) -> None:
        segs.append(Segment(len(segs), text, pause, scene))

    for blk in parse(script):
        if blk.kind == "scene":
            if segs:
                segs[-1].pause_after = max(segs[-1].pause_after, cfg.pause_scene)
            scene = blk.scene_id
        elif blk.kind == "para":
            if segs:
                segs[-1].pause_after = max(segs[-1].pause_after, cfg.pause_paragraph)
        elif blk.kind == "wait":
            if segs:
                segs[-1].pause_after += blk.value
        else:
            sentences = split_sentences(blk.text)
            # kısa cümleleri birleştir
            merged: list[str] = []
            for s in sentences:
                if merged and len(merged[-1]) < cfg.min_chars and len(merged[-1]) + 1 + len(s) <= cfg.max_chars:
                    merged[-1] = f"{merged[-1]} {s}"
                else:
                    merged.append(s)
            for s in merged:
                chunks = split_long(s, cfg.max_chars)
                for j, c in enumerate(chunks):
                    last = j == len(chunks) - 1
                    add(c, _terminal_pause(s, cfg) if last else cfg.pause_clause)
    return segs
