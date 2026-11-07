from __future__ import annotations
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import Config
from .engine import Engine
from .segmenter import Segment
from .timing import estimate_words


@dataclass
class Timed:
    idx: int
    scene: str
    text: str
    start: float
    end: float            # sesli kismin bitisi
    pause_after: float
    words: list[dict] = field(default_factory=list)


def _trim(x: np.ndarray, sr: int, cfg: Config) -> np.ndarray:
    thr = 10 ** (cfg.trim_db / 20)
    idx = np.flatnonzero(np.abs(x) > thr)
    if idx.size == 0:
        return x
    keep = int(cfg.trim_keep * sr)
    return x[max(0, idx[0] - keep): min(len(x), idx[-1] + keep + 1)]


def _fade(x: np.ndarray, sr: int, ms: float) -> np.ndarray:
    n = min(int(sr * ms / 1000), len(x) // 2)
    if n > 0:
        ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
        x = x.copy()
        x[:n] *= ramp
        x[-n:] *= ramp[::-1]
    return x


def _load_mono(path: Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return data.mean(axis=1), sr


def build(segs: list[Segment], eng: Engine, cfg: Config, job_dir: Path, progress) -> dict:
    job_dir.mkdir(parents=True, exist_ok=True)
    master = job_dir / "master.wav"
    timed: list[Timed] = []
    n_written = 0
    sr_ref: int | None = None
    wf: sf.SoundFile | None = None

    try:
        for seg in segs:
            wav, _, _ = eng.synth(seg.text)
            x, sr = _load_mono(wav)
            if sr_ref is None:
                sr_ref = sr
                wf = sf.SoundFile(str(master), "w", samplerate=sr, channels=1, subtype="PCM_16")
            elif sr != sr_ref:
                raise RuntimeError(f"Ornekleme hizi tutarsiz: {sr} != {sr_ref}")

            x = _fade(_trim(x, sr, cfg), sr, cfg.fade_ms)
            start = n_written / sr
            wf.write(x)
            n_written += len(x)
            end = n_written / sr

            pad = np.zeros(int(round(seg.pause_after * sr)), dtype=np.float32)
            wf.write(pad)
            n_written += len(pad)

            t = Timed(seg.idx, seg.scene, seg.text, start, end, seg.pause_after)
            t.words = estimate_words(seg.text, start, end)
            timed.append(t)
            progress(seg.idx + 1, len(segs))

            if eng.should_recycle():
                wf.close()
                raise MemoryError("RSS siniri asildi; surec yeniden baslatilmali")
    finally:
        if wf is not None and not wf.closed:
            wf.close()

    total = n_written / (sr_ref or 48000)
    scenes = _scenes(timed, total)
    tl = {
        "sample_rate": sr_ref,
        "duration": total,
        "engine": eng.engine_name,
        "segments": [asdict(t) for t in timed],
        "scenes": scenes,
    }
    (job_dir / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=2), encoding="utf-8")
    return tl


def _scenes(timed: list[Timed], total: float) -> list[dict]:
    order: list[str] = []
    first: dict[str, float] = {}
    for t in timed:
        if t.scene not in first:
            first[t.scene] = t.start
            order.append(t.scene)
    out = []
    for i, sid in enumerate(order):
        start = 0.0 if i == 0 else first[sid]
        end = total if i == len(order) - 1 else first[order[i + 1]]
        out.append({"id": sid, "start": start, "end": end, "duration": end - start})
    return out
