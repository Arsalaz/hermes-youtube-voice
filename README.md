# Hermes YouTube Voice Engine 🎙️

Hostinger KVM 1 VPS (1 vCPU, 4GB RAM, GPU yok) üzerinde **Hermes Agent**'ın YouTube videolarını otonom kurgulayıp seslendirmesi için tasarlanmış Türkçe kadın sesi sentezleme motoru.

## 🌟 Özellikler
* **Model:** Canberk Aslan'ın `EMA Lightning` modeli (8.6M parametre, ~34 MB).
* **Ses:** Yerli ve akıcı **Türkçe Kadın Sesi**.
* **Çevrimdışı & CPU-Only:** İnternete çıkmadan tamamen yerel işlemcide çalışır.
* **Asenkron Kuyruk:** Uzun YouTube videoları (~1500 kelime) arka planda üretilir, Hermes donmaz.
* **FFmpeg Montajı:** Otomatik loudness normalizasyonu (-16 LUFS), kelime bazlı SRT/ASS altyazı ve video birleştirme.
* **Yedek Motor:** Çevrimdışı EMA yüklenemezse otomatik **Edge-TTS** (`tr-TR-EmelNeural`) fallback desteği.

## 🚀 VPS Kurulumu (Hostinger KVM 1)
```bash
git clone https://github.com/Arsalaz/hermes-youtube-voice.git
cd hermes-youtube-voice
chmod +x install.sh
./install.sh
```

## 🛠️ Hermes Agent ile Kullanım
```bash
# 1. Senaryoyu gonder
hermes-voice submit --script senaryo.txt --default-image kapak.png --render

# 2. Durumu denetle
hermes-voice status <job_id>

# 3. Sonuclari al
hermes-voice result <job_id>
```
