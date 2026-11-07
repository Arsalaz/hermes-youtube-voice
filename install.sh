#!/usr/bin/env bash
set -euo pipefail

echo "=========================================================="
echo "  Hermes Voice Engine (EMA Lightning) VPS Kurulumu"
echo "  Hedef: Hostinger KVM 1 (1 vCPU, 4GB RAM, CPU-Only)"
echo "=========================================================="

# 1. Gerekli sistem paketleri
echo "[1/4] Sistem paketleri kontrol ediliyor..."
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends ffmpeg libsndfile1 fonts-dejavu-core python3-pip python3-venv

# 2. Swap kontrolü (4GB RAM KVM1 güvenliği için 2GB swap)
if [ ! -f /swapfile ]; then
    echo "[2/4] 2GB Swap olusturuluyor (OOM korumasi)..."
    sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    sudo sysctl vm.swappiness=10
fi

# 3. Docker veya Doğrudan Kurulum Seçeneği
echo "[3/4] Docker imaji derleniyor..."
if command -v docker >/dev/null 2>&1; then
    docker compose build
    docker compose up -d
    echo "Docker servisi ayakta: hermes-voice"
else
    echo "Docker bulunamadi, yerel virtualenv kuruluyor..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install torch --index-url https://download.pytorch.org/whl/cpu
    pip install ema-lightning --extra-index-url https://download.pytorch.org/whl/cpu
    pip install -e .
fi

# 4. Bench Testi
echo "[4/4] Hiz ve bellek testi (bench)..."
if command -v docker >/dev/null 2>&1; then
    docker compose exec -T hermes-voice hermes-voice bench
else
    hermes-voice bench
fi

echo "=========================================================="
echo "  Kurulum Basariyla Tamamlandi!"
echo "=========================================================="
