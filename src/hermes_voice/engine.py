from __future__ import annotations
import asyncio
import hashlib
import os
import time
from importlib import metadata
from pathlib import Path

from .config import Config

EXIT_RECYCLE = 75


def rss_mb() -> float:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except (OSError, FileNotFoundError):
        pass
    return 0.0


def model_tag() -> str:
    try:
        return "ema-lightning-" + metadata.version("ema-lightning")
    except Exception:
        return "ema-lightning-0.1"


class Engine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.tag = model_tag()
        self.tts = None
        self.engine_name = "ema-lightning"
        Path(cfg.cache_dir).mkdir(parents=True, exist_ok=True)
        self._init_tts()

    def _init_tts(self) -> None:
        try:
            import torch
            torch.set_num_threads(self.cfg.threads)
            torch.set_num_interop_threads(1)
            from ema_lightning import EMA
            self.tts = EMA()
            self.engine_name = "ema-lightning"
        except Exception as e:
            if self.cfg.use_fallback_edge_tts:
                print(f"[Engine] EMA Lightning yuklenemedi ({e}), Edge-TTS fallback devrede.", flush=True)
                self.engine_name = "edge-tts"
                self.tag = "edge-tts-tr-TR-EmelNeural"
            else:
                raise

    def key(self, text: str) -> str:
        return hashlib.sha1(f"{self.tag}\n{text}".encode("utf-8")).hexdigest()

    def path_for(self, text: str) -> Path:
        return Path(self.cfg.cache_dir) / f"{self.key(text)}.wav"

    def synth(self, text: str) -> tuple[Path, float, bool]:
        """(wav_yolu, sure_sn, onbellekten_mi) dondurur."""
        out = self.path_for(text)
        if out.exists() and out.stat().st_size > 44:
            return out, 0.0, True
        tmp = out.with_suffix(".tmp.wav")
        last: Exception | None = None
        for attempt in range(self.cfg.retries + 1):
            t0 = time.perf_counter()
            try:
                if self.engine_name == "ema-lightning" and self.tts is not None:
                    self.tts.say(text, path=str(tmp))
                else:
                    # Edge-TTS fallback
                    self._synth_edge_tts(text, tmp)
                if not tmp.exists() or tmp.stat().st_size <= 44:
                    raise RuntimeError("Bos ses dosyasi uretildi")
                os.replace(tmp, out)
                self._enforce_cache_limit()
                return out, time.perf_counter() - t0, False
            except Exception as e:
                last = e
                tmp.unlink(missing_ok=True)
                time.sleep(0.5)
        raise RuntimeError(f"Sentez basarisiz: {text[:60]!r} ({last})")

    def _synth_edge_tts(self, text: str, out_path: Path) -> None:
        import edge_tts
        mp3_tmp = out_path.with_suffix(".mp3")
        async def _run():
            communicate = edge_tts.Communicate(text, "tr-TR-EmelNeural")
            await communicate.save(str(mp3_tmp))
        asyncio.run(_run())
        # Convert mp3 to wav
        import soundfile as sf
        data, sr = sf.read(str(mp3_tmp))
        sf.write(str(out_path), data, sr)
        mp3_tmp.unlink(missing_ok=True)

    def _enforce_cache_limit(self) -> None:
        """Codex onerisi: Cache boyutunu max_cache_mb ile sinirla (LRU)."""
        cache_path = Path(self.cfg.cache_dir)
        files = list(cache_path.glob("*.wav"))
        total_bytes = sum(f.stat().st_size for f in files)
        limit_bytes = self.cfg.max_cache_mb * 1024 * 1024
        if total_bytes > limit_bytes:
            # En eski erisilen/degistirilen dosyalari sil
            files.sort(key=lambda f: f.stat().st_mtime)
            while total_bytes > limit_bytes and files:
                f_del = files.pop(0)
                sz = f_del.stat().st_size
                f_del.unlink(missing_ok=True)
                total_bytes -= sz

    def should_recycle(self) -> bool:
        return rss_mb() > self.cfg.rss_limit_mb
