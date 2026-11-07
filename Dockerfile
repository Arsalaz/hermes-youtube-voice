FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
    HV_DATA=/data HF_HOME=/data/hf TORCH_HOME=/data/torch

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg libsndfile1 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# torch CPU wheel'i once kur (yanlislikla CUDA wheel cekilmesini onler)
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install ema-lightning --extra-index-url https://download.pytorch.org/whl/cpu

WORKDIR /app
COPY pyproject.toml requirements.txt ./
COPY src ./src
RUN pip install .

RUN useradd -m -u 1000 hv && mkdir -p /data && chown -R hv:hv /data
USER hv
VOLUME ["/data"]
ENTRYPOINT ["hermes-voice"]
