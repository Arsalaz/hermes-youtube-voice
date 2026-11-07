# Hermes YouTube Voice: OpenAI Codex (6 Luna) Bağımsız İnceleme Raporu

> **Tarih:** 2026-11-07 22:54  
> **Ajan:** OpenAI Codex (`gpt-6-luna`)  
> **İncelenen:** `D:\Projeler\hermes-youtube-voice\mimari_tasarim.md`

---

## 1. Mimari Tutarlılık ve 1 vCPU / 4GB RAM Sınırlarında OOM Riski
- **Model Yükü:** EMA Lightning (8.6M parametre, ~34 MB) model ağırlıkları açısından son derece hafiftir. PyTorch CPU çalışma zamanı ile birlikte taban bellek kullanımı ~350-500 MB civarında kalacaktır.
- **Konteyner Bütçesi:** Claude'un tasarladığı 2 GB bellek sınırı ve `OMP_NUM_THREADS=1` / `torch.set_num_threads(1)` kısıtı KVM 1 sunucusu için doğru bir tercihtir.
- **Akışlı Disk Yazımı:** Sesin RAM'de biriktirilmeden segment segment diske yazılması (`master.wav` akışlı montajı), 10 dakikalık uzun videolarda bile OOM-killer riskini sıfıra yakın tutar.

## 2. Tek Çekirdekte Sentez Hızı ve Hermes Zaman Aşımı (Timeout)
- **Hız Beklentisi:** 10 dakikalık bir YouTube videosu (~1500 kelime, ~90-120 segment). 1 vCPU üzerinde tahmini üretim süresi 90 - 180 saniye arasındadır.
- **Asenkron Kuyruk Zorunluluğu:** Hermes'in Telegram/CLI araçları genelde 30-60 saniye sonra timeout verir. Claude'un tasarladığı **detached job mimarisi** (`hermes-voice submit` -> anında JobID dön -> `hermes-voice status` ile sorgula -> `hermes-voice result` ile al) Hermes'in donmasını engeller.

## 3. EMA Lightning ve Bağımlılıklar
- **Word Timings:** EMA Lightning dahili olarak kelime zamanlaması (word timing) sağlamaktadır; bu özellik SRT/altyazı üretiminde doğrudan kullanılmalıdır.
- **PyTorch CPU Wheel:** `pip install ema-lightning --extra-index-url https://download.pytorch.org/whl/cpu` kurulumu, devasa CUDA kütüphanelerini engelleyerek disk tasarrufu sağlar. Bağımlılıklar `requirements.txt` içinde sürüm sabitlenmelidir (pinned versions).

## 4. Hibrit / Fallback Stratejisi
- **Birincil:** Tamamen çevrimdışı ve yerel çalışan EMA Lightning (Türkçe Kadın Sesi).
- **Yedek (Fallback):** EMA Lightning yüklenemezse veya VPS aşırı CPU altındaysa, harici internet çıkışıyla ücretsiz çalışan **Edge-TTS** (`tr-TR-EmelNeural` kadın sesi).
- **Altın Kural:** Asla aynı videonun segmentleri arasında motor karıştırılmamalıdır (tüm video tek bir motorla üretilmelidir).

## 5. Disk, Önbellek ve Güvenlik
- **Disk Limiti:** 50 GB diskin 12 GB'ı doludur. Önbellek birikmesini önlemek için LRU (en eski kullanılanı silme) tabanlı azami 2 GB'lık önbellek üst sınırı uygulanmalıdır.
- **Güvenlik:** Video montajında FFmpeg'e aktarılan metin ve altyazı yolları sanitize edilmeli, komut enjeksiyonuna karşı argüman listesi olarak iletilmelidir.
