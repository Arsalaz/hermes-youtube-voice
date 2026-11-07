# PROJE DURUMU: Hermes YouTube Kadın Sesi & Video Entegrasyonu (Hostinger VPS)

## 📌 Proje Özeti
- **Amaç:** Hermes Agent'ın YouTube kanalını otonom yönetmesi, video kurgularken ihtiyaç duyduğu Türkçe kadın seslendirmesini (Voiceover) doğrudan Hostinger KVM 1 CPU VPS üzerinde üretmesi ve video üretim hattına entegre edilmesi.
- **Hedef Sunucu:** Hostinger KVM 1 (`srv2120899.hstgr.cloud`, 1 vCPU, 4GB RAM, 50GB NVMe, CPU kullanımı %4, Bellek %40, Docker container: Hermes Agent).
- **Referans:** Avenox'un `echo-ses-hermes` skill'i ve Canberk Aslan'ın `EMA Lightning` (8.6M parametre, ~34 MB, tek konuşmacı Türkçe kadın sesi, CPU üzerinde 100% offline çalışan DiT modeli).

## 🚀 Durum Panosu
- `[✔]` Keşif ve Avenox mimarisi tersine mühendisliği (EMA Lightning tespiti, parametre ve model teyidi).
- `[✔]` Çoklu Ajan Konsorsiyum Araştırması & Mimari Tasarımı (Antigravity + Claude Opus 5.5 + Codex 6 Luna).
- `[✔]` Mimari Tasarım Dokümantasyonu (`mimari_tasarim.md`, 1422 satır).
- `[✔]` Bağımsız Güvenlik, Performans ve VPS Stres Raporu (`codex_review.md`).
- `[▶]` Mert'e sunum ve onay doğrultusunda VPS kurulum adımları.
- `[ ]` VPS Kurulum Paketi & PyTorch CPU Optimizasyonu (`pip install ema-lightning --extra-index-url https://download.pytorch.org/whl/cpu`).
- `[ ]` YouTube Video Metin Parçalama (Chunking), Senkronizasyon ve FFmpeg Entegrasyon Betikleri.
- `[ ]` İkinci Beyin Raporlama & Git Senkronizasyonu.

## 👥 Ajan İş Bölümü
- **Gemini (Antigravity):** Keşif, literatür taraması, model künyesi, orkestrasyon, HANDSHAKE yönetimi.
- **Claude (Opus 5.5):** VPS üzerinde uçtan uca uzun video seslendirme mimarisi, Hermes skill tasarımı, script parçalama ve birleştirme mantığı.
- **Codex (6 Luna):** VPS kaynak tüketimi (1 vCPU, 4GB RAM), bellek darboğazı (OOM), concurrency, hata yönetimi ve yedekleme (fallback) denetimi.

