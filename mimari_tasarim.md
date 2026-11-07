# Hermes YouTube Voice: Mimari Tasarım (EMA Lightning, CPU-only VPS)

> **Handshake:** GOREV_HERMES_SES_01 · Claude (Opus 5.5 rolü) · 2026-11-07
> **Hedef dosya:** `D:\Projeler\hermes-youtube-voice\mimari_tasarim.md`
> **Not:** Bu doküman sohbet çıktısı olarak üretildi, dosya yazılmadı. Kaydı Antigravity veya Mert yapar.
> **Doğrulama durumu:** Hiçbir komut çalıştırılmadı. Aşağıdaki sayılar ve API varsayımları ölçülmemiştir. Bunlar §12'de "doğrulanacaklar" olarak listelidir.

---

## 1. Hedef ve kısıtlar

| Kısıt | Değer | Tasarım sonucu |
|---|---|---|
| CPU | 1 vCPU | Tek süreç, tek iş parçacığı, paralel sentez yok. |
| RAM | 4 GB (Hermes + Docker + OS dahil) | Sentez konteyneri 2 GB ile sınırlı. Ses diske akıtılır, RAM'de biriktirilmez. |
| Disk | 50 GB SSD | Segment önbelleği ve iş dizinleri için temizleme politikası gerekir. |
| GPU | Yok | `torch` CPU wheel. |
| Model | EMA Lightning, ~34 MB, tek konuşmacı | Model bir kez yüklenir, süreç boyunca açık kalır. Ses seçimi ve klonlama yoktur. |

**Tasarım ilkeleri**

1. **Deterministik ve devam ettirilebilir:** Her segment metin hash'iyle önbelleğe alınır. Çökme veya kesinti sonrası kaldığı yerden devam edilir.
2. **Zamanlama kaynağı = örnek (sample) sayısı:** Segment başlangıç ve bitiş süreleri yazılan ses örneklerinden hesaplanır, tahmin edilmez. Altyazı ve video bu değerlere bağlanır.
3. **Hermes'i bloklamayan iş modeli:** Uzun senaryo arka planda çalışır. Hermes `submit`, `status` ve `result` komutlarıyla iş yönetir.
4. **Tek çıktı sözleşmesi:** `master.wav`, `timeline.json`, `subs.srt`, `subs.ass`, `scenes.ffconcat`, `job.json`.

---

## 2. Üst düzey mimari

```
Hermes Agent (Docker)
   │  terminal tool: hermes-voice submit/status/result   (JSON stdout)
   ▼
┌─────────────────────────── hermes-voice (CLI, Python 3.11) ────────────────────────────┐
│ script.txt ──► segmenter ──► [Segment…] ──► engine (EMA, 1 thread) ──► cache/<hash>.wav │
│                                                │                                         │
│                                                ▼                                         │
│                                   assemble (trim + fade + pause, akışlı yazım)           │
│                                                │                                         │
│                      ┌─────────────────────────┼───────────────────────┐                 │
│                      ▼                         ▼                       ▼                 │
│                 master.wav               timeline.json          timing → subs.srt/.ass   │
│                      │                         │                                         │
│                      ▼                         ▼                                         │
│          ffmpeg: loudnorm 2-pass        scenes.ffconcat                                  │
│                      └─────────────┬───────────┘                                         │
│                                    ▼                                                     │
│                      ffmpeg: mux / (opsiyonel) altyazı yakma → out.mp4                   │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

### Depo yapısı

```
hermes-youtube-voice/
├─ PROJE_DURUMU.md
├─ mimari_tasarim.md
├─ pyproject.toml
├─ Dockerfile
├─ docker-compose.yml
├─ src/hermes_voice/
│  ├─ __init__.py
│  ├─ config.py        # Config dataclass, env override
│  ├─ markup.py        # senaryo işaretleri (@sahne, [[bekle]])
│  ├─ segmenter.py     # cümle/yan cümle bölme, pause atama
│  ├─ engine.py        # EMA sarmalayıcı, önbellek, RSS koruması
│  ├─ assemble.py      # trim/fade/pause, akışlı WAV, timeline
│  ├─ timing.py        # kelime zamanlaması (karakter ağırlıklı)
│  ├─ subtitles.py     # SRT + ASS (karaoke)
│  ├─ ffmpeg_ops.py    # loudnorm, ffconcat, mux
│  ├─ jobs.py          # job.json, kilit, detach
│  └─ cli.py
├─ skills/hermes-voice/SKILL.md
└─ tests/
```

---

## 3. Konfigürasyon

```python
# src/hermes_voice/config.py
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
    # --- yollar ---
    data_dir: str = field(default_factory=lambda: os.environ.get("HV_DATA", "/data"))

    @property
    def cache_dir(self) -> str:
        return os.path.join(self.data_dir, "cache")

    @property
    def jobs_dir(self) -> str:
        return os.path.join(self.data_dir, "jobs")
```

---

## 4. Metin segmentasyonu

### 4.1 Senaryo işaretleri (`markup.py`)

| Söz dizimi | Anlam |
|---|---|
| Boş satır | Paragraf sonu, `pause_paragraph` uygulanır. |
| `@sahne giris` | Yeni sahne başlar. Önceki segmentin sonuna `pause_scene` eklenir ve `timeline.scenes` kaydı açılır. |
| `[[bekle 1.5]]` (tek satır) | Önceki segmentin sonuna ek 1.5 sn sessizlik. |
| `# Başlık`, `**kalın**` | Markdown işaretleri temizlenir, metin okunur. |

```python
# src/hermes_voice/markup.py
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
```

### 4.2 Bölme mantığı (`segmenter.py`)

Kademeli üç seviye uygulanır:

1. **Cümle sınırı:** `. ! ? …` ile biten ve sonraki sözcüğü büyük harf, rakam veya tırnakla başlayan sözcük cümleyi bitirir. Kısaltma listesi (`Dr.`, `Prof.`, `vb.`, `vs.`, `örn.`…) ve sıra sayıları (`3. sınıf`) cümle sonu sayılmaz.
2. **Uzun cümle:** `max_chars` aşılırsa `, ; : — –` sonrasından açgözlü paketlenir. Parça hâlâ uzunsa sözcük sınırından bölünür.
3. **Kısa cümle birleştirme:** `min_chars` altındaki cümle, toplam `max_chars`'ı aşmıyorsa sonraki cümleyle (aynı paragraf içinde) birleştirilir. Çok kısa girdilerde model prozodisi kötüleşebilir. Bu varsayım §12'de test edilecek.

Her segmente **pause_after** atanır:

| Segment sonu | Sessizlik |
|---|---|
| `.` | 0.45 sn |
| `?` | 0.50 sn |
| `!` | 0.45 sn |
| `…` | 0.70 sn |
| yan cümle (`,` `;` `:` `—`) | 0.18 sn |
| paragraf sonu | `max(mevcut, 0.90)` |
| sahne sınırı | `max(mevcut, 1.20)` |
| `[[bekle x]]` | mevcut + x |

```python
# src/hermes_voice/segmenter.py
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
```

> Not: `pause_after` alanı paragraf ve sahne işleme sırasında yerinde güncellenir. Bu yüzden `Segment` mutable bırakıldı.

---

## 5. Sentez motoru (`engine.py`)

Kritik noktalar:

- Model **bir kez** yüklenir (`EMA()`). Her segment için yeniden yüklenmez.
- `torch.set_num_threads(1)` ile tek vCPU'da thread çekişmesi önlenir.
- Önbellek anahtarı = `sha1(model_sürümü + normalize_edilmemiş metin)`. Aynı cümle tekrar sentezlenmez.
- Segment tamamlanınca `.tmp` dosyası `os.replace` ile atomik olarak yerine alınır. Yarım dosya önbelleğe girmez.
- RSS sınırı aşılırsa süreç `EXIT_RECYCLE (75)` ile çıkar. `jobs.py` bunu yakalayıp çocuk süreci yeniden başlatır. Önbellek sayesinde kaldığı yerden devam eder.

```python
# src/hermes_voice/engine.py
from __future__ import annotations
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
    except OSError:
        pass
    return 0.0


def model_tag() -> str:
    try:
        return "ema-lightning-" + metadata.version("ema-lightning")
    except metadata.PackageNotFoundError:
        return "ema-lightning-unknown"


class Engine:
    def __init__(self, cfg: Config):
        import torch  # geç import: --help hızlı kalsın
        torch.set_num_threads(cfg.threads)
        torch.set_num_interop_threads(1)
        from ema_lightning import EMA  # API: EMA().say(text, path=...)
        self.cfg = cfg
        self.tts = EMA()
        self.tag = model_tag()
        Path(cfg.cache_dir).mkdir(parents=True, exist_ok=True)

    def key(self, text: str) -> str:
        return hashlib.sha1(f"{self.tag}\n{text}".encode("utf-8")).hexdigest()

    def path_for(self, text: str) -> Path:
        return Path(self.cfg.cache_dir) / f"{self.key(text)}.wav"

    def synth(self, text: str) -> tuple[Path, float, bool]:
        """(wav_yolu, süre_sn, önbellekten_mi) döndürür."""
        out = self.path_for(text)
        if out.exists() and out.stat().st_size > 44:
            return out, 0.0, True
        tmp = out.with_suffix(".tmp.wav")
        last: Exception | None = None
        for attempt in range(self.cfg.retries + 1):
            t0 = time.perf_counter()
            try:
                self.tts.say(text, path=str(tmp))
                if not tmp.exists() or tmp.stat().st_size <= 44:
                    raise RuntimeError("boş ses dosyası üretildi")
                os.replace(tmp, out)
                return out, time.perf_counter() - t0, False
            except Exception as e:  # noqa: BLE001
                last = e
                tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Sentez başarısız: {text[:60]!r}… ({last})")

    def should_recycle(self) -> bool:
        return rss_mb() > self.cfg.rss_limit_mb
```

---

## 6. Ses birleştirme ve zaman çizelgesi (`assemble.py`)

Adımlar:

1. Her segment WAV'ı mono float32 okunur. Örnekleme hızı otomatik algılanır (varsayılmaz). Segmentler arasında farklıysa hata verilir.
2. Baş ve sondaki sessizlik `trim_db` eşiğine göre kırpılır, `trim_keep` pay bırakılır. Böylece segment sınırında modelden gelen rastgele sessizlik atılır ve pause tamamen kontrol altında olur.
3. 6 ms fade-in ve fade-out uygulanır (tık sesi önlenir).
4. Pause kadar sıfır örnek yazılır.
5. Çıktı `soundfile.SoundFile` ile **akışlı** yazılır. 1 saatlik 24 kHz ses RAM'de ~345 MB tutmaz, tek seferde yalnız bir segment bellekte kalır.
6. Zamanlar **örnek sayacından** hesaplanır: `t = n_samples / sr`.

```python
# src/hermes_voice/assemble.py
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
    end: float            # sesli kısmın bitişi
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
                raise RuntimeError(f"Örnekleme hızı tutarsız: {sr} != {sr_ref}")

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
                raise MemoryError("RSS sınırı aşıldı; süreç yeniden başlatılmalı")
    finally:
        if wf is not None and not wf.closed:
            wf.close()

    total = n_written / sr_ref
    scenes = _scenes(timed, total)
    tl = {
        "sample_rate": sr_ref,
        "duration": total,
        "segments": [asdict(t) for t in timed],
        "scenes": scenes,
    }
    (job_dir / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=2), encoding="utf-8")
    return tl


def _scenes(timed: list[Timed], total: float) -> list[dict]:
    """Sahneler ardışık ve boşluksuz: sahne[i].end == sahne[i+1].start."""
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
```

**RSS yeniden başlatma mantığı:** `MemoryError` `cli.py` içinde yakalanır ve `EXIT_RECYCLE` ile çıkılır. `jobs.py` supervisor'ı süreci yeniden başlatır. Önbellekteki segmentler hızla geçilir, kalan kısım sentezlenir. `master.wav` baştan yazılsa da önbellek okuması sentezden çok daha ucuzdur.

---

## 7. Kelime zamanlaması ve altyazı

### 7.1 Strateji

| Seviye | Yöntem | Doğruluk | Maliyet | Durum |
|---|---|---|---|---|
| **A: Segment zamanı** | Örnek sayacı | Kesin | Sıfır | Varsayılan, SRT satırları buna bağlı. |
| **B: Kelime tahmini** | Segment içinde karakter ve noktalama ağırlıklı dağıtım | Yaklaşık (±100–200 ms) | Sıfır | Varsayılan karaoke ve altyazı bölme. |
| **C: Zorlamalı hizalama** | CTC/Whisper tiny ile hizalama | Yüksek | 1 vCPU'da ağır, ek ~1 GB RAM | Bu fazda kapsam dışı. |

Segmentler kısa (≤220 karakter, genelde 3–10 sn) olduğundan B seviyesindeki hata segment sınırıyla sınırlanır ve birikmez. Bu, B'yi pratik hale getirir.

### 7.2 Kelime tahmini (`timing.py`)

Ağırlık = harf sayısı + 1.0, noktalama kuyruğu için ek: virgül/noktalı virgül +2.5, cümle sonu +4.0. Tahmin Türkçe hece yapısıyla uyumlu olsun diye ünlü sayısı da katılır: ağırlık = ünlü sayısı × 2 + ünsüz sayısı × 0.7. Türkçe hece sayısı ünlü sayısına eşittir, bu da süre ile iyi korelasyon verir.

```python
# src/hermes_voice/timing.py
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
```

> Rakam ve sembol içeren sözcükler (örn. `2026`, `%15`) konuşulurken uzar (iki bin yirmi altı). Bu yüzden ağırlıkları `len*1.2` ile kaba şekilde büyütülür. Normalizer'ın gerçek çıktısını okuyabilirsek (§12) ağırlık bu metinden hesaplanmalıdır.

### 7.3 SRT ve ASS (`subtitles.py`)

Kuyruk (cue) oluşturma kuralları:

- Cue en fazla `sub_max_lines × sub_max_line` = 76 karakter.
- Cue en fazla 6 sn. Cümle sonunda veya segment sınırında kapanır.
- Cue en az 0.8 sn görünür. Kısa cue, pause içine uzatılır ama bir sonraki cue'nun başlangıcını geçemez.
- Satır bölme: yaklaşık ortadan, en yakın sözcük sınırında.

```python
# src/hermes_voice/subtitles.py
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
    """karaoke=True: \\kf ile kelime kelime dolan vurgu (SecondaryColour -> PrimaryColour)."""
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
```

> **Bilinen sınırlama:** `_wrap` içindeki orta nokta bulma mantığı basit tutuldu. 2 satırlık cue'larda çirkin bölünme olursa tek satırlık kuyruklara düşürülüp birim testle sabitlenmelidir. Karaoke modunda satır kırma libass'ın `WrapStyle: 0` otomatik sarmasına bırakıldı.

---

## 8. FFmpeg stratejisi

### 8.1 Genel kurallar (1 vCPU)

- Tüm ffmpeg çağrıları: `nice -n 10 ffmpeg -hide_banner -nostdin -threads 1`.
- Çözünürlük 1280×720, 25 fps. Statik görsel için `-tune stillimage`, `-preset veryfast`, `-crf 23`.
- **AAC kodlaması yalnız en sonda, bir kez** yapılır. Ara dosyalar WAV (PCM) tutulur. AAC kodlayıcı gecikmesi (~1024 örnek) ve çift kodlama kaymasını önler.
- Ses süresi video süresinin referansıdır. Video ses süresine göre kurulur, tersi değil.

### 8.2 Loudness (iki geçiş, doğrusal)

Hedef: YouTube için −16 LUFS (stereo içerik için yaygın hedef), −1.5 dBTP.

```bash
# Geçiş 1: ölçüm (JSON stderr'in sonunda)
nice -n 10 ffmpeg -hide_banner -nostdin -threads 1 -i master.wav \
  -af "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json" -f null - 2> loud1.txt

# Geçiş 2: ölçülen değerlerle doğrusal normalizasyon + 48 kHz + stereo
nice -n 10 ffmpeg -hide_banner -nostdin -threads 1 -y -i master.wav \
  -af "loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=<I>:measured_TP=<TP>:measured_LRA=<LRA>:measured_thresh=<thresh>:offset=<offset>:linear=true:print_format=summary,aresample=48000" \
  -ac 2 -c:a pcm_s16le master_48k.wav
```

`linear=true` süreyi değiştirmez. Zaman çizelgesi geçerli kalır.

### 8.3 Sahne dosyası (`scenes.ffconcat`)

Her sahneye bir görsel atanır (`--scene-map sahne=gorsel.png`). Süreler `timeline.scenes[].duration`'dan gelir:

```
ffconcat version 1.0
file /data/jobs/J1/assets/giris.png
duration 12.480
file /data/jobs/J1/assets/konu1.png
duration 41.920
file /data/jobs/J1/assets/konu1.png   # concat demuxer: son dosya tekrar yazılmalı
```

### 8.4 Video üretimi + mux (tek geçiş, soft altyazı)

```bash
nice -n 10 ffmpeg -hide_banner -nostdin -threads 1 -y \
  -f concat -safe 0 -i scenes.ffconcat -i master_48k.wav \
  -vf "fps=25,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p" \
  -c:v libx264 -preset veryfast -crf 23 -tune stillimage -g 50 \
  -c:a aac -b:a 192k -shortest -movflags +faststart \
  out.mp4
```

### 8.5 Altyazıyı videoya yakmak (opsiyonel, yeniden kodlama gerekir)

```bash
nice -n 10 ffmpeg -hide_banner -nostdin -threads 1 -y \
  -f concat -safe 0 -i scenes.ffconcat -i master_48k.wav \
  -vf "fps=25,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,subtitles=subs.ass:fontsdir=/usr/share/fonts,format=yuv420p" \
  -c:v libx264 -preset veryfast -crf 23 -tune stillimage \
  -c:a aac -b:a 192k -shortest -movflags +faststart out_burned.mp4
```

YouTube'a **SRT ayrıca yüklenebilir**, bu da yakmadan daha ucuz ve kalıcı olarak düzenlenebilir. Yakma yalnız karaoke tarzı efekt isteniyorsa kullanılmalı.

### 8.6 Hazır video üzerine ses bindirme (video zaten varsa)

```bash
# Sessiz video + ses; video yeniden kodlanmaz
ffmpeg -hide_banner -nostdin -y -i video.mp4 -i master_48k.wav \
  -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart out.mp4
```

Video ses süresinden kısaysa son kareyi dondurmak için:
`-vf "tpad=stop_mode=clone:stop_duration=<fark_sn>"` (bu durumda `-c:v copy` kullanılamaz, yeniden kodlanır).

### 8.7 `ffmpeg_ops.py`

```python
# src/hermes_voice/ffmpeg_ops.py
from __future__ import annotations
import json
import re
import subprocess
from pathlib import Path

from .config import Config

BASE = ["nice", "-n", "10", "ffmpeg", "-hide_banner", "-nostdin", "-threads", "1"]


def _run(args: list[str]) -> str:
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg hata ({p.returncode}): {p.stderr[-800:]}")
    return p.stderr


def loudnorm(src: Path, dst: Path, cfg: Config) -> dict:
    tgt = f"I={cfg.lufs}:TP={cfg.tp}:LRA=11"
    err = _run(BASE + ["-i", str(src), "-af", f"loudnorm={tgt}:print_format=json", "-f", "null", "-"])
    m = json.loads(re.findall(r"\{[^{}]*\}", err)[-1])
    af = (
        f"loudnorm={tgt}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
        f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
        f"offset={m['target_offset']}:linear=true,aresample={cfg.final_sr}"
    )
    _run(BASE + ["-y", "-i", str(src), "-af", af, "-ac", "2", "-c:a", "pcm_s16le", str(dst)])
    return m


def write_ffconcat(tl: dict, scene_map: dict[str, str], default_img: str | None, dst: Path) -> None:
    lines = ["ffconcat version 1.0"]
    last = None
    for sc in tl["scenes"]:
        img = scene_map.get(sc["id"]) or default_img
        if not img:
            raise ValueError(f"Sahne için görsel yok: {sc['id']}")
        lines += [f"file '{Path(img).as_posix()}'", f"duration {sc['duration']:.3f}"]
        last = img
    lines.append(f"file '{Path(last).as_posix()}'")  # concat demuxer son-duration hatası için
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render(concat: Path, audio: Path, out: Path, cfg: Config, ass: Path | None = None) -> None:
    vf = (f"fps={cfg.fps},scale={cfg.video_w}:{cfg.video_h}:force_original_aspect_ratio=decrease,"
          f"pad={cfg.video_w}:{cfg.video_h}:(ow-iw)/2:(oh-ih)/2")
    if ass:
        vf += f",subtitles={ass.name}"
    vf += ",format=yuv420p"
    cwd_args = ["-f", "concat", "-safe", "0", "-i", str(concat), "-i", str(audio)]
    _run(BASE + ["-y"] + cwd_args + [
        "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)])
```

> `subtitles=` filtresi yolunda `:` ve `\` kaçış sorunları oluşur. Bu yüzden yakma çağrısında işlem dizini iş klasörü yapılmalı ve filtreye yalnız dosya adı verilmelidir. `render()` çağıran taraf `cwd=job_dir` ile çalıştırmalı veya `subprocess.run(..., cwd=...)` eklenmelidir.

---

## 9. İş yönetimi ve CLI

### 9.1 İş modeli

Uzun bir senaryonun sentez süresi (gerçek zaman çarpanı RTF'ye bağlı, §12) dakikalar–saatler sürebilir. Hermes'in terminal çağrısı zaman aşımına uğrayabileceğinden iş **detached** çalışır:

```
/data/jobs/<job_id>/
├─ job.json        # {state, progress, error, started, finished, params}
├─ script.txt
├─ master.wav, master_48k.wav
├─ timeline.json, subs.srt, subs.ass, scenes.ffconcat
├─ out.mp4         # render istendiyse
└─ log.txt
```

`state`: `queued | running | recycling | done | failed`.
`/data/.lock` üzerinde `fcntl.flock`: aynı anda tek sentez işi. İkinci `submit` kuyruğa alınır (state=`queued`, kilit bekler).

### 9.2 `jobs.py`

```python
# src/hermes_voice/jobs.py
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
        raise FileNotFoundError(f"iş yok: {job_id}")
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
    """Worker'ı çocuk süreçte çalıştırır; EXIT_RECYCLE gelirse yeniden başlatır."""
    for _ in range(max_restarts):
        rc = subprocess.call([sys.executable, "-m", "hermes_voice.cli", "_run", job_id, *argv_tail])
        if rc != EXIT_RECYCLE:
            return rc
        update(cfg, job_id, state="recycling")
    return 1
```

### 9.3 `cli.py`

Tüm komutlar **tek satır JSON** stdout'a yazar (`{"ok": true, ...}` veya `{"ok": false, "error": "..."}`). Bu, Hermes'in çıktıyı güvenle ayrıştırması içindir. Günlükler stderr veya `log.txt`'ye gider.

| Komut | İşlev |
|---|---|
| `bench [--text ...]` | Model yükleme süresi, RTF, tepe RSS ölçer (§12). |
| `plan --script f.txt` | Sentez yapmadan segment listesi, karakter sayısı ve tahmini süreyi döndürür. |
| `submit --script f.txt [--scene-map a=img.png …] [--render] [--burn-subs]` | İş oluşturur, arka planda başlatır, `job_id` döndürür. |
| `status JOB` | `state`, `progress`, `eta` döndürür. |
| `result JOB` | Üretilen dosya yolları ve süre. |
| `clean [--older-than 7d]` | Eski işleri ve önbelleği temizler. |

```python
# src/hermes_voice/cli.py
from __future__ import annotations
import argparse
import fcntl
import json
import shutil
import sys
import time
from pathlib import Path

from . import jobs
from .config import Config
from .engine import EXIT_RECYCLE


def out(obj: dict, code: int = 0) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.exit(code)


def cmd_plan(a, cfg):
    from .segmenter import segment
    text = Path(a.script).read_text(encoding="utf-8")
    segs = segment(text, cfg)
    chars = sum(len(s.text) for s in segs)
    est = chars / 14.0 + sum(s.pause_after for s in segs)   # ~14 karakter/sn konuşma, kaba tahmin
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
    eng.tts.say(text, path=str(p))
    synth = time.perf_counter() - t1
    info = sf.info(str(p))
    out({"ok": True, "load_s": round(load, 2), "synth_s": round(synth, 2),
         "audio_s": round(info.duration, 2), "rtf": round(synth / info.duration, 3),
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
    if j.get("state") == "running" and j.get("progress", 0) > 0.02:
        el = time.time() - j["started"]
        eta = round(el / j["progress"] - el)
    out({"ok": True, "job_id": a.job, "state": j["state"], "progress": round(j.get("progress", 0), 3),
         "eta_s": eta, "error": j.get("error")})


def cmd_result(a, cfg):
    j = jobs.read(cfg, a.job)
    if j["state"] != "done":
        out({"ok": False, "error": f"iş tamamlanmadı: {j['state']}"}, 2)
    d = jobs.job_dir(cfg, a.job)
    files = {n: str(d / n) for n in
             ("master_48k.wav", "timeline.json", "subs.srt", "subs.ass", "scenes.ffconcat", "out.mp4")
             if (d / n).exists()}
    out({"ok": True, "job_id": a.job, "duration_s": j.get("duration"), "files": files})


def cmd_clean(a, cfg):
    days = float(a.older_than_days)
    cutoff = time.time() - days * 86400
    removed = 0
    for d in Path(cfg.jobs_dir).glob("*"):
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d)
            removed += 1
    cache_removed = 0
    for f in Path(cfg.cache_dir).glob("*.wav"):
        if f.stat().st_atime < cutoff:
            f.unlink()
            cache_removed += 1
    out({"ok": True, "jobs_removed": removed, "cache_removed": cache_removed})


def cmd_worker(a, cfg):
    """Detached giriş: kilidi bekler, supervisor'ı çalıştırır, durumu yazar."""
    Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
    with open(Path(cfg.data_dir) / ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)           # tek seferde tek sentez
        jobs.update(cfg, a.job, state="running", started=time.time())
        rc = jobs.supervise(cfg, a.job, a.rest)
        if rc != 0 and jobs.read(cfg, a.job)["state"] != "failed":
            jobs.update(cfg, a.job, state="failed", error=f"worker çıkış kodu {rc}")
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
    except Exception as e:  # noqa: BLE001
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
    except Exception as e:  # noqa: BLE001
        out({"ok": False, "error": f"{type(e).__name__}: {e}"}, 1)


if __name__ == "__main__":
    main()
```

### 9.4 `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "hermes-voice"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
  "numpy",
  "soundfile",
  # torch ve ema-lightning Dockerfile'da CPU index ile ayrıca kurulur
]

[project.scripts]
hermes-voice = "hermes_voice.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
```

---

## 10. Docker / VPS optimizasyonu

### 10.1 Dockerfile

```dockerfile
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
    HV_DATA=/data HF_HOME=/data/hf TORCH_HOME=/data/torch

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg libsndfile1 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# torch CPU wheel'i önce kur (yanlışlıkla CUDA wheel çekilmesin)
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install ema-lightning --extra-index-url https://download.pytorch.org/whl/cpu

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install .

RUN useradd -m -u 1000 hv && mkdir -p /data && chown hv:hv /data
USER hv
VOLUME ["/data"]
ENTRYPOINT ["hermes-voice"]
```

### 10.2 docker-compose.yml

```yaml
services:
  hermes-voice:
    build: .
    image: hermes-voice:0.1
    # Hermes bu konteynerde `docker exec` / `docker compose run` ile komut çalıştırır.
    # Servis kalıcı tutulmak istenirse boş bir komutla uyutulur:
    entrypoint: ["sleep", "infinity"]
    cpus: "1.0"
    mem_limit: 2g
    memswap_limit: 3g          # küçük bir swap payı; OOM-kill yerine yavaşlama
    pids_limit: 256
    environment:
      HV_THREADS: "1"
      HV_RSS_LIMIT_MB: "1600"
      HV_DATA: /data
    volumes:
      - hv_data:/data          # cache + jobs + model önbelleği
    restart: unless-stopped
volumes:
  hv_data:
```

Hermes aynı Docker ağında/ana makinede `docker compose exec hermes-voice hermes-voice <komut>` ile çağırır. Alternatif olarak Hermes konteynerine `/data` volume'u paylaştırılıp CLI doğrudan Hermes imajına kurulabilir. Bu durumda tek konteyner yeter ama bağımlılıklar (torch ~200 MB+) Hermes imajına karışır. Ayrı konteyner önerilir.

### 10.3 VPS ayarları

| Konu | Öneri |
|---|---|
| Swap | Ana makinede 2 GB swapfile (`fallocate -l 2G /swapfile`, `swapon`). 4 GB RAM'de ani tepe için güvenlik. `vm.swappiness=10`. |
| Öncelik | Sentez ve ffmpeg `nice -n 10` ile çalışır. Hermes'in yanıt verebilirliği korunur. |
| Eşzamanlılık | `flock` ile tek iş. Sentez ve ffmpeg aynı anda koşmaz (iş içinde ardışıktır). |
| Disk | 24 kHz mono PCM16 ≈ 2.7 MB/dk. 10 dk video için ses ~27 MB, `master_48k.wav` stereo ~115 MB, `out.mp4` ~50–150 MB. Önbellek segmentleri toplamı ~ aynı büyüklükte. `clean --older-than-days 7` ile cron'a bağla. |
| Model önbelleği | `HF_HOME`/`TORCH_HOME` volume içinde. Konteyner yeniden kurulunca model tekrar indirilmez (modelin indirme mi, paket içi mi olduğu §12'de doğrulanacak). |
| İndirme şeffaflığı | Proje kuralı gereği imaj kurulumu ve ilk model indirmesi sırasında dosya adı, boyut, % ve hız Mert'e bildirilir. `pip install --progress-bar on` ve `docker build --progress=plain` kullanılır. |
| Zaman aşımı | Hermes tarafında uzun komut yok: `submit` anında döner, ilerleme `status` ile sorgulanır. |

### 10.4 Bellek bütçesi (tahmini, ölçülmemiş)

| Bileşen | Tahmin |
|---|---|
| OS + Docker daemon | ~400–600 MB |
| Hermes Agent konteyneri | ~500–1000 MB |
| hermes-voice süreci (torch CPU + model) | ~400–800 MB |
| ffmpeg (720p, 1 thread) | ~150–300 MB |

Toplam 4 GB içinde sığması beklenir. `bench` komutu tepe RSS'i ölçüp bunu doğrulayacak.

---

## 11. Hermes Skill arayüzü

> **Varsayım:** Hermes skill formatı olarak `SKILL.md` + YAML frontmatter (name, description) kabul edildi. Kurulu Hermes sürümünün gerçek skill şeması bu görev kapsamında incelenmedi. Kurulumdan önce Hermes'in skill dokümanıyla karşılaştırılmalı, gerekirse yalnız frontmatter alanları uyarlanmalıdır. CLI sözleşmesi (JSON stdout) formattan bağımsızdır.

### `skills/hermes-voice/SKILL.md`

````markdown
---
name: hermes-voice
description: Türkçe kadın sesiyle YouTube video seslendirmesi üretir (EMA Lightning, CPU). Senaryo metninden ses (WAV), altyazı (SRT/ASS), zaman çizelgesi ve isteğe bağlı MP4 üretir. Uzun işler arka planda çalışır.
---

# hermes-voice

Türkçe senaryo metnini seslendirir. Tek ses vardır (Türkçe kadın); ses seçimi yoktur.

## Çağrı biçimi
Tüm komutlar tek satır JSON döndürür: `{"ok": true, ...}` veya `{"ok": false, "error": "..."}`.
Komut öneki: `docker compose -f /opt/hermes-youtube-voice/docker-compose.yml exec -T hermes-voice hermes-voice`
Dosya yolları `/data` altındadır (konteyner içi).

## Senaryo yazım kuralları
- Her cümleyi noktalama ile bitir. Sayıları ve kısaltmaları normal yaz, normalleştirme modelin içindedir.
- Boş satır = paragraf sonu (uzun sessizlik).
- `@sahne <kimlik>` tek satırda = yeni sahne (video görseli bu kimlikle eşlenir).
- `[[bekle 1.5]]` tek satırda = ek sessizlik (saniye).
- Markdown işaretleri (`#`, `**`) temizlenir.

## İş akışı
1. Senaryoyu `/data/inbox/<ad>.txt` dosyasına yaz.
2. (İsteğe bağlı) Süre tahmini: `plan --script /data/inbox/<ad>.txt`
   → `{"ok":true,"segments":N,"chars":C,"est_audio_sec":S,"scenes":[...]}`
3. Başlat: `submit --script /data/inbox/<ad>.txt [--render] [--burn-subs] [--default-image /data/assets/bg.png] [--scene-map giris=/data/assets/a.png]`
   → `{"ok":true,"job_id":"..."}`. Hemen döner. Bekleme, sonuç için `status` kullan.
4. İlerleme: `status <job_id>` → `state` (queued|running|recycling|done|failed), `progress` (0–1), `eta_s`.
   `status` komutunu en fazla 60 sn arayla sorgula, sık sorma.
5. Bitince: `result <job_id>` → `files` altında `master_48k.wav`, `timeline.json`, `subs.srt`, `subs.ass`, `scenes.ffconcat`, `out.mp4` (render istendiyse) yolları.

## Kurallar
- Aynı anda yalnız bir sentez işi çalışır, diğerleri sıraya girer.
- `state=failed` ise `error` alanını kullanıcıya aktar, aynı `submit` tekrar çağrılabilir (segmentler önbellekte, kaldığı yerden devam eder).
- `--render` için her sahneye görsel gerekir (`--scene-map` veya `--default-image`).
- Altyazıyı videoya gömmek (`--burn-subs`) yeniden kodlama gerektirir ve daha yavaştır. YouTube'a SRT ayrıca yüklemek daha ucuzdur.
- Disk temizliği: `clean --older-than-days 7`.

## Örnek
```
submit --script /data/inbox/video12.txt --default-image /data/assets/bg.png --render
status 20261107-231500-a1b2c3
result 20261107-231500-a1b2c3
```
````

### Hermes tarafı entegrasyon seçenekleri

| Seçenek | Açıklama | Öneri |
|---|---|---|
| **A: Terminal aracı + SKILL.md** | Hermes shell komutunu çalıştırır (yukarıdaki). Ek kod yok. | **Varsayılan.** |
| B: Python araç sarmalayıcı | `submit/status/result` için ince `subprocess` fonksiyonları. | Hermes araç kaydı Python fonksiyonu istiyorsa. |
| C: HTTP servisi | FastAPI ile aynı işlevler. | Gerekmedikçe yapma: 1 vCPU'da ekstra süreç ve RAM, saldırı yüzeyi. |

Seçenek B için örnek:

```python
# hermes_tools/voice.py  (Hermes tarafında, gerekirse)
import json, subprocess

_PREFIX = ["docker", "compose", "-f", "/opt/hermes-youtube-voice/docker-compose.yml",
           "exec", "-T", "hermes-voice", "hermes-voice"]


def _call(*args: str) -> dict:
    p = subprocess.run([*_PREFIX, *args], capture_output=True, text=True, timeout=60)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"ok": False, "error": (p.stderr or p.stdout)[-400:]}


def submit(script_path: str, render: bool = False, default_image: str | None = None) -> dict:
    a = ["submit", "--script", script_path]
    if render: a.append("--render")
    if default_image: a += ["--default-image", default_image]
    return _call(*a)

def status(job_id: str) -> dict: return _call("status", job_id)
def result(job_id: str) -> dict: return _call("result", job_id)
```

---

## 12. Doğrulanacaklar ve açık riskler

Aşağıdakiler bu görevde **çalıştırılıp doğrulanmadı**, tasarım bunlara varsayımla dayanır. Uygulama fazında önce `bench` ile kontrol edilmelidir.

| # | Konu | Neden önemli | Nasıl doğrulanır |
|---|---|---|---|
| 1 | **RTF (gerçek zaman çarpanı)** | Toplam üretim süresini belirler. 10 dk video ≈ 1500 sözcük ≈ 10–11 bin karakter. Süre = 600 sn × RTF. | `hermes-voice bench` (VPS üzerinde, boşta). |
| 2 | **Çıkış örnekleme hızı** | Kod hızı dosyadan okuyor, ama 48 kHz'e yükseltme kalitesi ve boyut hesabı buna bağlı. | `bench` çıktısındaki `sample_rate`. |
| 3 | **`say()` imzası** | Verilen: `tts.say(text, path=output.wav)`. Başka parametre (hız, ton) var mı bilinmiyor. | `help(EMA.say)`. Hız ayarı varsa `Config`'e eklenir. |
| 4 | **Maksimum girdi uzunluğu** | `max_chars=220` varsayım. Model daha uzun cümleyi kaldırabilir veya kesebilir. | 100/200/400/800 karakterlik metinlerle dinleme ve süre testi. |
| 5 | **Çok kısa girdide kalite** | `min_chars=28` birleştirme varsayımı. | "Evet." gibi girdilerle dinleme. |
| 6 | **Bellek sızıntısı** | RSS koruması bu varsayıma dayanıyor. Sızıntı yoksa yeniden başlatma devreye girmez, zararı yok. | 500+ segmentlik sentezde `rss_mb` eğrisi. |
| 7 | **Thread güvenliği / çoklu süreç** | Tasarım zaten tek süreç, tek thread. | Gerekmez. |
| 8 | **Normalizer çıktısı erişimi** | Kelime zamanlamasının rakam/kısaltma doğruluğu normalleşmiş metne bağlı. | `ema_lightning` / `normalizer-tr` içinde normalize fonksiyonu var mı bak. Varsa `timing.py` ağırlığı normalleşmiş metinden hesaplansın. |
| 9 | **Model dosyasının kaynağı** | Paket içinde mi, ilk çağrıda indirilen mi? İnternet yoksa kurulum kırılır. Volume ve `HF_HOME` ayarı buna göre. | İlk `EMA()` çağrısında ağ trafiği izle. |
| 10 | **Sistem bağımlılıkları** | Modelin `espeak-ng` vb. isteyip istemediği bilinmiyor. | İlk kurulum hata mesajı. Gerekirse Dockerfile `apt` listesine ekle. |
| 11 | **Hermes skill şeması** | §11'deki `SKILL.md` formatı varsayım. | Kurulu Hermes sürümünün skill dokümanı. |
| 12 | **Lisans** | Apache 2.0 olduğu görev bağlamında belirtilmiş. Ses kaynağı (eğitim verisi/ses sahibi) izni YouTube monetizasyonu için ayrıca kontrol edilmeli. | Proje deposunun lisans ve model kartı. |
| 13 | **Kelime zamanlaması doğruluğu** | B seviyesi tahmin. Karaoke kayması gözle fark edilirse C seviyesi (hizalama) gerekir. | 3 örnek videoda göz kontrolü. |
| 14 | **`loudnorm` tekrarlanabilirliği** | Çok kısa içerikte (<3 sn) ölçüm güvenilmez olabilir. | Kısa girdide JSON çıktısını kontrol et. |

### Bilinen kod sınırlamaları

- `_wrap` (altyazı satır bölme) basit. Birim testle sabitlenmeli.
- `render()` içindeki `subtitles=` filtresi için `cwd=job_dir` ayarlanmalı (§8.7 notu).
- `cmd_run` içinde `MemoryError` sonrası `master.wav` baştan yazılır. Doğru ama ilk segmentlerin önbellekten okunması zaman alır.
- `clean`, önbellekte erişim zamanına (`atime`) bakıyor. Bazı dosya sistemleri `noatime` ile bağlıdır, bu durumda `st_mtime` kullanılmalı.
- `fcntl` yalnız Linux'ta çalışır. Windows'ta geliştirme/test için `jobs.supervise` mantığı ayrı sınanmalı (VPS hedefi Linux).
- Birim test iskeleti yazılmadı. Codex tarafında `segmenter`, `timing`, `subtitles` (saf fonksiyonlar, model gerektirmez) için önerilir.

---

## 13. Uygulama sırası (öneri)

| Faz | İş | Çıktı | Bitiş kriteri |
|---|---|---|---|
| 0 | VPS'te imaj kurulumu (§10), indirme ilerlemesi raporlanır | Çalışan konteyner | `bench` JSON döndürür. RTF, RSS ve sample rate kaydedilir. |
| 1 | `segmenter`, `markup`, `timing`, `subtitles` + birim testler | Model gerektirmeyen çekirdek | `pytest` yeşil. |
| 2 | `engine` + `assemble` + `plan` komutu | `master.wav` + `timeline.json` | 3 dk örnek senaryo dinlenir, segment sınırları temiz. |
| 3 | `ffmpeg_ops` + `loudnorm` + `render` | `out.mp4` | Video ve ses süresi farkı < 40 ms (`ffprobe`). |
| 4 | `jobs`, `submit/status/result`, kilit, recycle | Detached çalışma | Bilerek `kill -9` sonrası `submit` kaldığı yerden devam eder. |
| 5 | `SKILL.md` + Hermes entegrasyonu | Hermes'ten uçtan uca üretim | Hermes, tek komutla 10 dk'lık senaryodan MP4 üretir. |
| 6 | Karşılaştırmalı değerlendirme: B → C hizalama gerekir mi? | Karar notu | Karaoke kayması ölçülür. |

Codex review önerisi: Faz 1 testleri için **5.6 Terra**, Faz 4 (`jobs`, kilit, atomik yazım) için **6 Luna**, geri kalanı **5.6 Luna** standart diff review.

---

## HANDSHAKE Sonuç

- **Yapılanlar:** Dosya yazma aracı kullanılmadan tam mimari doküman üretildi. Kapsam: modüler CLI tasarımı (§2–3, §9), segmentasyon ve sessizlik payları (§4), sentez motoru ve önbellek (§5), birleştirme ve zaman çizelgesi (§6), kelime zamanlaması ve SRT/ASS (§7), FFmpeg komutları (§8), Docker/VPS optimizasyonu (§10), Hermes skill arayüzü (§11).
- **Çalıştırılan komutlar ve çıktıları (kanıt):** Yok. Hiçbir komut çalıştırılmadı, kod derlenmedi ve test edilmedi. Kod taslakları yazım düzeyindedir. `EMA.say` imzası, RTF, örnekleme hızı ve RAM tüketimi ölçülmedi.
- **Açık sorunlar / sonraki adım:** §12'deki 14 doğrulama maddesi. İlk adım VPS'te Faz 0 (`bench`). Dokümanın `D:\Projeler\hermes-youtube-voice\mimari_tasarim.md` yoluna kaydedilmesi ve `HANDSHAKE_CLAUDE.md` durumunun güncellenmesi Antigravity'ye veya Mert'e kalır. Codex review ve birim testleri Faz 1'de.
