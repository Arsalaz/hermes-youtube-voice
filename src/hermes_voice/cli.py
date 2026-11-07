from __future__ import annotations
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import jobs
from .config import Config
from .engine import EXIT_RECYCLE


def _lock_file(f):
    try:
        import fcntl
        fcntl.flock(f, fcntl.LOCK_EX)
    except (ImportError, AttributeError):
        pass  # Windows ortaminda flock atlanir


def out(obj: dict, code: int = 0) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.exit(code)


def cmd_plan(a, cfg):
    from .segmenter import segment
    text = Path(a.script).read_text(encoding="utf-8")
    segs = segment(text, cfg)
    chars = sum(len(s.text) for s in segs)
    est = chars / 14.0 + sum(s.pause_after for s in segs)
    out({"ok": True, "segments": len(segs), "chars": chars, "est_audio_sec": round(est, 1),
         "scenes": sorted({s.scene for s in segs})})


def cmd_bench(a, cfg):
    from .engine import Engine, rss_mb
    import soundfile as sf
    t0 = time.perf_counter()
    eng = Engine(cfg)
    load = time.perf_counter() - t0
    text = a.text or "Merhaba, bu bir hız ölçümüdür. Yapay zekâ ile üretilen ses, kısa bir sınama için kullanılıyor."
    p = Path(cfg.data_dir) / "bench.wav"
    t1 = time.perf_counter()
    eng.synth(text)
    synth = time.perf_counter() - t1
    info = sf.info(str(eng.path_for(text)))
    out({"ok": True, "engine": eng.engine_name, "load_s": round(load, 2), "synth_s": round(synth, 2),
         "audio_s": round(info.duration, 2), "rtf": round(synth / max(0.01, info.duration), 3),
         "sample_rate": info.samplerate, "rss_mb": round(rss_mb())})


def cmd_submit(a, cfg):
    jid = jobs.new_id()
    d = jobs.job_dir(cfg, jid)
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(a.script, d / "script.txt")
    tail = []
    for sm in a.scene_map or []:
        tail += ["--scene-map", sm]
    if a.default_image:
        tail += ["--default-image", a.default_image]
    if a.render:
        tail.append("--render")
    if a.burn_subs:
        tail.append("--burn-subs")
    jobs.update(cfg, jid, state="queued", progress=0.0, params=tail, created=time.time())
    pid = jobs.spawn_detached(cfg, jid, tail)
    out({"ok": True, "job_id": jid, "pid": pid})


def cmd_status(a, cfg):
    j = jobs.read(cfg, a.job)
    eta = None
    if j.get("state") == "running" and j.get("progress", 0) > 0.02 and "started" in j:
        el = time.time() - j["started"]
        eta = round(el / j["progress"] - el)
    out({"ok": True, "job_id": a.job, "state": j["state"], "progress": round(j.get("progress", 0), 3),
         "eta_s": eta, "error": j.get("error")})


def cmd_result(a, cfg):
    j = jobs.read(cfg, a.job)
    if j["state"] != "done":
        out({"ok": False, "error": f"is tamamlanmadi: {j['state']}"}, 2)
    d = jobs.job_dir(cfg, a.job)
    files = {n: str(d / n) for n in
             ("master_48k.wav", "timeline.json", "subs.srt", "subs.ass", "scenes.ffconcat", "out.mp4")
             if (d / n).exists()}
    out({"ok": True, "job_id": a.job, "duration_s": j.get("duration"), "files": files})


def cmd_clean(a, cfg):
    days = float(a.older_than_days)
    cutoff = time.time() - days * 86400
    removed = 0
    if Path(cfg.jobs_dir).exists():
        for d in Path(cfg.jobs_dir).glob("*"):
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
    cache_removed = 0
    if Path(cfg.cache_dir).exists():
        for f in Path(cfg.cache_dir).glob("*.wav"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
                cache_removed += 1
    out({"ok": True, "jobs_removed": removed, "cache_removed": cache_removed})


def cmd_worker(a, cfg):
    """Detached giris: kilidi bekler, supervisor'i calistirir."""
    Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
    with open(Path(cfg.data_dir) / ".lock", "w") as lk:
        _lock_file(lk)
        jobs.update(cfg, a.job, state="running", started=time.time())
        rc = jobs.supervise(cfg, a.job, a.rest)
        if rc != 0 and jobs.read(cfg, a.job)["state"] != "failed":
            jobs.update(cfg, a.job, state="failed", error=f"worker cikis kodu {rc}")
    sys.exit(rc)


def cmd_run(a, cfg):
    from .assemble import build
    from .engine import Engine
    from .ffmpeg_ops import loudnorm, write_ffconcat, render
    from .segmenter import segment
    from .subtitles import write_srt, write_ass

    d = jobs.job_dir(cfg, a.job)
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene-map", action="append", default=[])
    ap.add_argument("--default-image")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--burn-subs", action="store_true")
    o = ap.parse_args(a.rest)
    try:
        segs = segment((d / "script.txt").read_text(encoding="utf-8"), cfg)
        eng = Engine(cfg)
        prog = lambda i, n: jobs.update(cfg, a.job, progress=i / n * 0.9)
        try:
            tl = build(segs, eng, cfg, d, prog)
        except MemoryError:
            sys.exit(EXIT_RECYCLE)
        write_srt(tl, d / "subs.srt", cfg)
        write_ass(tl, d / "subs.ass", cfg)
        loudnorm(d / "master.wav", d / "master_48k.wav", cfg)
        if o.render:
            smap = dict(kv.split("=", 1) for kv in o.scene_map)
            write_ffconcat(tl, smap, o.default_image, d / "scenes.ffconcat")
            render(d / "scenes.ffconcat", d / "master_48k.wav", d / "out.mp4", cfg,
                   ass=(d / "subs.ass") if o.burn_subs else None)
        jobs.update(cfg, a.job, state="done", progress=1.0, finished=time.time(), duration=tl["duration"])
    except SystemExit:
        raise
    except Exception as e:
        jobs.update(cfg, a.job, state="failed", error=str(e))
        raise


def main():
    cfg = Config()
    ap = argparse.ArgumentParser(prog="hermes-voice")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan"); s.add_argument("--script", required=True); s.set_defaults(f=cmd_plan)
    s = sub.add_parser("bench"); s.add_argument("--text"); s.set_defaults(f=cmd_bench)
    s = sub.add_parser("submit")
    s.add_argument("--script", required=True)
    s.add_argument("--scene-map", action="append", metavar="SAHNE=GORSEL")
    s.add_argument("--default-image")
    s.add_argument("--render", action="store_true")
    s.add_argument("--burn-subs", action="store_true")
    s.set_defaults(f=cmd_submit)
    s = sub.add_parser("status"); s.add_argument("job"); s.set_defaults(f=cmd_status)
    s = sub.add_parser("result"); s.add_argument("job"); s.set_defaults(f=cmd_result)
    s = sub.add_parser("clean"); s.add_argument("--older-than-days", default="7"); s.set_defaults(f=cmd_clean)
    for name, fn in (("_worker", cmd_worker), ("_run", cmd_run)):
        s = sub.add_parser(name); s.add_argument("job"); s.add_argument("rest", nargs=argparse.REMAINDER); s.set_defaults(f=fn)
    a = ap.parse_args()
    try:
        a.f(a, cfg)
    except SystemExit:
        raise
    except Exception as e:
        out({"ok": False, "error": f"{type(e).__name__}: {e}"}, 1)


if __name__ == "__main__":
    main()
