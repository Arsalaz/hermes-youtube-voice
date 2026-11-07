from __future__ import annotations
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .config import Config
from .engine import EXIT_RECYCLE


def new_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def job_dir(cfg: Config, job_id: str) -> Path:
    return Path(cfg.jobs_dir) / job_id


def read(cfg: Config, job_id: str) -> dict:
    p = job_dir(cfg, job_id) / "job.json"
    if not p.exists():
        raise FileNotFoundError(f"is bulunamadi: {job_id}")
    return json.loads(p.read_text(encoding="utf-8"))


def update(cfg: Config, job_id: str, **kw) -> dict:
    d = job_dir(cfg, job_id)
    p = d / "job.json"
    cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    cur.update(kw)
    cur["updated"] = time.time()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return cur


def spawn_detached(cfg: Config, job_id: str, argv_tail: list[str]) -> int:
    d = job_dir(cfg, job_id)
    log = open(d / "log.txt", "ab")
    p = subprocess.Popen(
        [sys.executable, "-m", "hermes_voice.cli", "_worker", job_id, *argv_tail],
        stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True,
    )
    return p.pid


def supervise(cfg: Config, job_id: str, argv_tail: list[str], max_restarts: int = 20) -> int:
    """Worker'i cocuk surecte calistirir; EXIT_RECYCLE gelirse yeniden baslatir."""
    for _ in range(max_restarts):
        rc = subprocess.call([sys.executable, "-m", "hermes_voice.cli", "_run", job_id, *argv_tail])
        if rc != EXIT_RECYCLE:
            return rc
        update(cfg, job_id, state="recycling")
    return 1
