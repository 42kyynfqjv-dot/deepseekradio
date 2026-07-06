# Deploying The Frequency on the box

Target: the Netcup VPS (real x86, AVX2 — Kokoro runs at full speed).

## 1. System deps

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip ffmpeg icecast2
```

During the `icecast2` install, set the source/admin passwords (used in
`config.yaml` -> `stream` and `icecast.xml`).

## 2. App

```bash
git clone <this repo> kaos && cd kaos
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # add OPENROUTER_API_KEY
```

## 3. Kokoro TTS

```bash
pip install kokoro-onnx soundfile numpy
mkdir -p kokoro
# download the model + voices into kokoro/ (see kokoro-onnx releases):
#   kokoro/kokoro.onnx
#   kokoro/voices.bin
```

Benchmark it before trusting 24/7:

```bash
python -m src.orchestrator --once --live
# check: did it keep up? aim for >1x realtime so the buffer never starves.
```

## 4. Streaming

Icecast serves the public listen URL; a source client (liquidsoap or a simple
ffmpeg loop) reads `audio_buffer/*.wav` in order and pushes to the mount.

Minimal ffmpeg source (concatenates the buffer to the Icecast mount):

```bash
ffmpeg -re -f concat -safe 0 -i playlist.txt \
  -c:a libmp3lame -b:a 96k -content_type audio/mpeg \
  icecast://source:PASSWORD@127.0.0.1:8000/kaos.mp3
```

Public stream: `http://<box-ip>:8000/kaos.mp3`

## 5. Run it 24/7 (systemd)

See `deploy/kaos.service`. It runs the orchestrator loop, which keeps the buffer
~45 min ahead of playback so slow TTS bursts never cause dead air.

```bash
sudo cp deploy/kaos.service /etc/systemd/system/
sudo systemctl enable --now kaos
journalctl -u kaos -f
```

## Safety on 2GB boxes

Add swap so an OOM degrades gracefully instead of killing the process:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```
