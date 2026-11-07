from __future__ import annotations
import re
from dataclasses import dataclass

_SCENE = re.compile(r"^@sahne\s+([\w\-]+)\s*$", re.IGNORECASE)
_WAIT = re.compile(r"^\[\[bekle\s+([0-9]+(?:\.[0-9]+)?)\]\]\s*$", re.IGNORECASE)
_MD = re.compile(r"(\*\*|__|`|^#+\s*|^>\s*|^[-*]\s+)")


@dataclass
class Block:
    kind: str            # "text" | "scene" | "wait" | "para"
    text: str = ""
    value: float = 0.0
    scene_id: str = ""


def parse(script: str) -> list[Block]:
    """Ham senaryoyu blok akışına çevirir."""
    blocks: list[Block] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            blocks.append(Block("text", text=" ".join(buf).strip()))
            buf.clear()

    for raw in script.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if m := _SCENE.match(line):
            flush()
            blocks.append(Block("scene", scene_id=m.group(1)))
        elif m := _WAIT.match(line):
            flush()
            blocks.append(Block("wait", value=float(m.group(1))))
        elif not line:
            flush()
            blocks.append(Block("para"))
        else:
            buf.append(_MD.sub("", line).strip())
    flush()
    return blocks
