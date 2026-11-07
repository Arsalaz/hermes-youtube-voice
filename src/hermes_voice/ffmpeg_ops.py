from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .config import Config

# Linux VPS uzerinde nice ile calisir, Windows test ortaminda dogrudan ffmpeg kullanir
_HAS_NICE = shutil.which("nice") is not None
BASE = ["nice", "-n", "10", "ffmpeg", "-hide_banner", "-nostdin", "-threads", "1"] if _HAS_NICE else ["ffmpeg", "-hide_banner", "-nostdin", "-threads", "1"]


def _run(args: list[str], cwd: Path | None = None) -> str:
    p = subprocess.run(args, capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg hata ({p.returncode}): {p.stderr[-800:]}")
    return p.stderr


def loudnorm(src: Path, dst: Path, cfg: Config) -> dict:
    tgt = f"I={cfg.lufs}:TP={cfg.tp}:LRA=11"
    err = _run(BASE + ["-i", str(src), "-af", f"loudnorm={tgt}:print_format=json", "-f", "null", "-"])
    m_list = re.findall(r"\{[^{}]*\}", err)
    if not m_list:
        # Loudnorm JSON bulunamazsa direkt kopyala
        shutil.copy(src, dst)
        return {"input_i": cfg.lufs}
    m = json.loads(m_list[-1])
    af = (
        f"loudnorm={tgt}:measured_I={m.get('input_i', -16)}:measured_TP={m.get('input_tp', -1.5)}:"
        f"measured_LRA={m.get('input_lra', 11)}:measured_thresh={m.get('input_thresh', -26)}:"
        f"offset={m.get('target_offset', 0)}:linear=true,aresample={cfg.final_sr}"
    )
    _run(BASE + ["-y", "-i", str(src), "-af", af, "-ac", "2", "-c:a", "pcm_s16le", str(dst)])
    return m


def write_ffconcat(tl: dict, scene_map: dict[str, str], default_img: str | None, dst: Path) -> None:
    lines = ["ffconcat version 1.0"]
    last = None
    for sc in tl["scenes"]:
        img = scene_map.get(sc["id"]) or default_img
        if not img:
            raise ValueError(f"Sahne icin gorsel bulunamadi: {sc['id']}")
        lines += [f"file '{Path(img).as_posix()}'", f"duration {sc['duration']:.3f}"]
        last = img
    if last:
        lines.append(f"file '{Path(last).as_posix()}'")  # concat demuxer son-duration hatasi icin
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render(concat: Path, audio: Path, out: Path, cfg: Config, ass: Path | None = None) -> None:
    vf = (f"fps={cfg.fps},scale={cfg.video_w}:{cfg.video_h}:force_original_aspect_ratio=decrease,"
          f"pad={cfg.video_w}:{cfg.video_h}:(ow-iw)/2:(oh-ih)/2")
    job_dir = out.parent
    if ass:
        # Yol kargasasini onlemek icin dosya adi verilip job_dir cwd yapilir
        vf += f",subtitles={ass.name}"
    vf += ",format=yuv420p"
    cwd_args = ["-f", "concat", "-safe", "0", "-i", str(concat.name), "-i", str(audio.name)]
    _run(BASE + ["-y"] + cwd_args + [
        "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out.name)],
        cwd=job_dir)
