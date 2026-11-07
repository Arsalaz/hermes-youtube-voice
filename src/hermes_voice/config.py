from __future__ import annotations
import os
from dataclasses import dataclass, field


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _i(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class Config:
    # --- segmentasyon ---
    max_chars: int = field(default_factory=lambda: _i("HV_MAX_CHARS", 220))
    min_chars: int = field(default_factory=lambda: _i("HV_MIN_CHARS", 28))
    # --- sessizlik payları (saniye) ---
    pause_period: float = 0.45
    pause_question: float = 0.50
    pause_exclaim: float = 0.45
    pause_ellipsis: float = 0.70
    pause_clause: float = 0.18      # virgül/noktalı virgül/iki nokta ile bölünen yan cümle
    pause_paragraph: float = 0.90   # boş satır
    pause_scene: float = 1.20       # @sahne sınırı
    # --- ses ---
    trim_db: float = -45.0          # baş/son sessizlik eşiği
    trim_keep: float = 0.040        # kırpmadan sonra bırakılan pay
    fade_ms: float = 6.0
    # --- motor ---
    threads: int = field(default_factory=lambda: _i("HV_THREADS", 1))
    rss_limit_mb: int = field(default_factory=lambda: _i("HV_RSS_LIMIT_MB", 1600))
    retries: int = 2
    use_fallback_edge_tts: bool = field(default_factory=lambda: os.environ.get("HV_FALLBACK_EDGE", "1") == "1")
    # --- altyazı ---
    sub_max_line: int = 38
    sub_max_lines: int = 2
    sub_max_dur: float = 6.0
    sub_min_dur: float = 0.8
    # --- çıktı ---
    final_sr: int = 48000
    lufs: float = -16.0
    tp: float = -1.5
    video_w: int = 1280
    video_h: int = 720
    fps: int = 25
    # --- yollar ve limitler ---
    data_dir: str = field(default_factory=lambda: os.environ.get("HV_DATA", "./data"))
    max_cache_mb: int = 2048  # Codex önerisi: max 2GB LRU cache

    @property
    def cache_dir(self) -> str:
        return os.path.join(self.data_dir, "cache")

    @property
    def jobs_dir(self) -> str:
        return os.path.join(self.data_dir, "jobs")
