---
name: hermes-voice
description: Turkce kadin sesiyle YouTube video seslendirmesi uretir (EMA Lightning, CPU). Senaryo metninden ses (WAV), altyazi (SRT/ASS), zaman cizelgesi ve istege bagli MP4 uretir.
---

# hermes-voice

Turkce YouTube video senaryolarini dogal kadin sesiyle seslendirir ve video montajina hazirlar.

## Cagri Formati
Komutlar tek satir JSON dondurur (`{"ok": true, ...}`).
Calistirma komutu:
```bash
docker compose -f /opt/hermes-youtube-voice/docker-compose.yml exec -T hermes-voice hermes-voice <alt_komut>
```
(Veya dogrudan yerel CLI kuruluysa: `hermes-voice <alt_komut>`)

## Komutlar ve Kullanim
1. **Planlama (Sure & Sahne Tahmini):**
   ```bash
   hermes-voice plan --script /data/script.txt
   ```
2. **Is Baslatma (Asenkron Kuyruk):**
   ```bash
   hermes-voice submit --script /data/script.txt --default-image /data/bg.png --render
   ```
   Hemen `{"ok": true, "job_id": "20261107-231500-a1b2c3"}` doner.
3. **Durum Sorgulama:**
   ```bash
   hermes-voice status <job_id>
   ```
4. **Sonuc Dosyalarini Alma:**
   ```bash
   hermes-voice result <job_id>
   ```
   Cikti dosyalari: `master_48k.wav`, `timeline.json`, `subs.srt`, `subs.ass`, `scenes.ffconcat`, `out.mp4`.
