#!/usr/bin/env bash
set -u
ROOT="$(pwd)"
ASSETS="$ROOT/assets"
mkdir -p "$ASSETS"

say() { printf "\n\033[1m%s\033[0m\n" "$*"; }
ok()  { printf "  ✅ %s\n" "$*"; }
warn(){ printf "  ⚠️  %s\n" "$*"; }
err() { printf "  ❌ %s\n" "$*"; }

summary=()

# -------------------------------
# Azure 체크
# -------------------------------
say "[A] Azure Neural TTS 체크"
AZ_MOD_OK=1
python - <<'PY' 2>/dev/null || AZ_MOD_OK=0
import importlib; import sys
importlib.import_module('azure.cognitiveservices.speech')
print('OK')
PY

if [ $AZ_MOD_OK -eq 1 ]; then
  ok "파이썬 SDK 설치됨 (azure.cognitiveservices.speech)"
else
  warn "SDK 미설치 → 설치:  pip install azure-cognitiveservices-speech"
fi

if [ "${AZURE_TTS_KEY:-}" != "" ] && [ "${AZURE_TTS_REGION:-}" != "" ]; then
  ok "환경변수 감지: AZURE_TTS_KEY / AZURE_TTS_REGION"
  # 스모크(키/네트워크 필요). 실패해도 전체 스크립트는 계속 진행.
  python - <<'PY' || echo "  (Azure 스모크 실패: 키/네트워크/보이스 이름 점검)"
import os, sys
try:
    import azure.cognitiveservices.speech as speechsdk
except Exception as e:
    print("SDK import 실패:", e); sys.exit(1)
key=os.environ.get("AZURE_TTS_KEY"); region=os.environ.get("AZURE_TTS_REGION")
voice=os.environ.get("AZURE_TTS_VOICE","ko-KR-SunHiNeural")
out="assets/azure_smoke.wav"
speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
speech_config.speech_synthesis_voice_name = voice
audio_config = speechsdk.audio.AudioOutputConfig(filename=out)
synth = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
r = synth.speak_text_async("안녕하세요. Azure TTS 점검입니다.").get()
if r.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
    print("OK:", out)
else:
    print("Azure 합성 실패:", r.reason)
    if r.cancellation_details: print(r.cancellation_details.reason, r.cancellation_details.error_details)
    sys.exit(2)
PY
  [ -f "$ASSETS/azure_smoke.wav" ] && ok "스모크 생성: assets/azure_smoke.wav"
else
  warn "환경변수 없음 → export AZURE_TTS_KEY=... ; export AZURE_TTS_REGION=..."
fi

# -------------------------------
# Piper 체크
# -------------------------------
say "[B] Piper(오프라인) 체크"
if command -v piper >/dev/null 2>&1; then
  ok "piper 바이너리 존재: $(piper --version 2>&1 | head -n1)"
  shopt -s nullglob
  models=("$HOME/piper"/*.onnx)
  if [ ${#models[@]} -eq 0 ]; then
    warn "Piper .onnx 모델 없음 → ~/piper/ 에 한국어 모델(.onnx) 파일을 내려받으세요."
    warn "공식 릴리스에서 ko-KR 계열 모델을 받으면 됩니다. (예: ko-KR-*.onnx)"
  else
    ok "모델 감지: ${models[0]##*/}"
    printf "안녕하세요. 파이퍼 음성 합성 점검입니다." | piper -m "${models[0]}" \
      --length_scale 1.0 --noise_scale 0.33 --noise_w 0.5 \
      -f "$ASSETS/piper_smoke.wav" >/dev/null 2>&1 \
      && ok "스모크 생성: assets/piper_smoke.wav" \
      || warn "합성 실패(모델/옵션 변경 필요)"
  fi
else
  warn "piper 미설치. Ubuntu면:  sudo apt install piper  (또는 릴리스 바이너리 다운로드)"
fi

# -------------------------------
# Melo/XTTS 체크
# -------------------------------
say "[C] Melo/XTTS(고품질 오프라인) 체크"
MELO_OK=1
python - <<'PY' 2>/dev/null || MELO_OK=0
import importlib
try:
    importlib.import_module('melo.api')  # MeloTTS
    print('MELO_IMPORT_OK')
except Exception:
    pass
try:
    importlib.import_module('TTS')       # Coqui TTS (XTTSv2 등)
    print('COQUI_TTS_IMPORT_OK')
except Exception:
    pass
PY

if [ $MELO_OK -eq 1 ]; then
  ok "로컬에 Melo 또는 Coqui TTS가 import 가능"
  # 무거운 가중치 다운로드가 걸릴 수 있어 기본은 import만 확인.
  warn "실제 합성은 모델 다운로드/세팅 필요. (컨테이너/conda 권장: Python 3.10 + Torch 2.2~2.3)"
else
  warn "로컬 파이썬에 Melo/XTTS 미구성."
  warn "권장: 컨테이너/conda로 별도 환경 고정 (py3.10)."
fi

# -------------------------------
# 요약
# -------------------------------
say "요약"
test -f "$ASSETS/azure_smoke.wav" && summary+=("Azure: OK (assets/azure_smoke.wav)") || summary+=("Azure: 미완 (SDK/KEY/네트워크 확인)")
if command -v piper >/dev/null 2>&1; then
  if [ -f "$ASSETS/piper_smoke.wav" ]; then summary+=("Piper: OK (assets/piper_smoke.wav)"); else summary+=("Piper: 모델 필요 또는 합성 실패"); fi
else summary+=("Piper: 미설치"); fi
[ $MELO_OK -eq 1 ] && summary+=("Melo/XTTS: import OK (합성은 모델 세팅 필요)") || summary+=("Melo/XTTS: 미구성")

for s in "${summary[@]}"; do echo " - $s"; done
