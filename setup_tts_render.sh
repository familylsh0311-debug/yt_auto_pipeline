#!/usr/bin/env bash
set -Eeuo pipefail
trap 'echo "[ERR] line:$LINENO cmd:$BASH_COMMAND" >&2' ERR

cd "$HOME/creator/kits/yt_auto_pipeline"

echo "[*] ensure base tools"
sudo apt update -y
sudo apt install -y git curl unzip build-essential python3-dev libsndfile1

echo "[*] venv"
if [ ! -d "$HOME/.venv/topic" ]; then
  python3 -m venv "$HOME/.venv/topic"
fi
source "$HOME/.venv/topic/bin/activate"
python -m pip install -U pip wheel setuptools

echo "[*] (optional but recommended) install torch (CPU)"
# GPU가 아니면 CPU 휠로 설치해 두면 Melo/OV2가 편해요.
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio

echo "[*] install MeloTTS from git"
python -m pip install "git+https://github.com/myshell-ai/MeloTTS.git"

echo "[*] install OpenVoice (editable)"
if [ ! -d OpenVoice ]; then
  git clone https://github.com/myshell-ai/OpenVoice.git
fi
python -m pip install -e OpenVoice

echo "[*] install client utils"
python -m pip install requests websocket-client soundfile pydub

echo "[*] download OV2 checkpoints (≈300MB)"
mkdir -p OpenVoice/checkpoints_v2
pushd OpenVoice >/dev/null
if [ ! -f checkpoints_v2/.downloaded_v2 ]; then
  curl -fL -o /tmp/ov2.zip "https://myshell-public-repo-hosting.s3.amazonaws.com/openvoice/checkpoints_v2_0417.zip"
  unzip -o /tmp/ov2.zip -d checkpoints_v2
  touch checkpoints_v2/.downloaded_v2
fi
popd >/dev/null

echo "[OK] setup_tts_render done"

