from __future__ import annotations
import re
from pathlib import Path

from .config import Config


def _srt_ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _ass_ts(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def _cues(tl: dict, cfg: Config) -> list[list[dict]]:
    cap = cfg.sub_max_line * cfg.sub_max_lines
    cues: list[list[dict]] = []
    for seg in tl["segments"]:
        cur: list[dict] = []
        for w in seg["words"]:
            txt_len = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
            too_long = txt_len > cap
            too_slow = cur and (w["e"] - cur[0]["s"]) > cfg.sub_max_dur
            if cur and (too_long or too_slow):
                cues.append(cur)
                cur = []
            cur.append(w)
            if re.search(r"[.!?…][\"”’')\]]*$", w["w"]):
                cues.append(cur)
                cur = []
        if cur:
            cues.append(cur)
    return cues


def _wrap(words: list[dict], cfg: Config) -> str:
    text = " ".join(w["w"] for w in words)
    if len(text) <= cfg.sub_max_line:
        return text
    mid, best, pos = len(text) / 2, 0, 0
    for i, w in enumerate(words[:-1]):
        pos += len(w["w"]) + 1
        if abs(pos - mid) < abs(sum(len(x["w"]) + 1 for x in words[:best + 1]) - mid) or best == 0:
            best = i
    return " ".join(w["w"] for w in words[:best + 1]) + "\n" + " ".join(w["w"] for w in words[best + 1:])


def _timed_cues(tl: dict, cfg: Config) -> list[tuple[float, float, list[dict]]]:
    cues = _cues(tl, cfg)
    out = []
    for i, c in enumerate(cues):
        s, e = c[0]["s"], c[-1]["e"]
        nxt = cues[i + 1][0]["s"] if i + 1 < len(cues) else tl["duration"]
        if e - s < cfg.sub_min_dur:
            e = min(s + cfg.sub_min_dur, nxt)
        out.append((s, e, c))
    return out


def write_srt(tl: dict, path: Path, cfg: Config) -> None:
    lines = []
    for n, (s, e, c) in enumerate(_timed_cues(tl, cfg), 1):
        lines.append(f"{n}\n{_srt_ts(s)} --> {_srt_ts(e)}\n{_wrap(c, cfg)}\n")
    path.write_text("\n".join(lines), encoding="utf-8")


_ASS_HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,DejaVu Sans,{fs},&H00FFFFFF,&H0000D7FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,{mv},1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""


def write_ass(tl: dict, path: Path, cfg: Config, karaoke: bool = True) -> None:
    head = _ASS_HEAD.format(w=cfg.video_w, h=cfg.video_h, fs=int(cfg.video_h * 0.055), mv=int(cfg.video_h * 0.07))
    ev = []
    for s, e, c in _timed_cues(tl, cfg):
        if karaoke:
            parts = []
            for w in c:
                cs = max(1, int(round((w["e"] - w["s"]) * 100)))
                parts.append(f"{{\\kf{cs}}}{w['w']} ")
            text = "".join(parts).rstrip()
        else:
            text = _wrap(c, cfg).replace("\n", "\\N")
        ev.append(f"Dialogue: 0,{_ass_ts(s)},{_ass_ts(e)},Default,,0,0,0,,{text}")
    path.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")
