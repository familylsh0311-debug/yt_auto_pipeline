#!/usr/bin/env bash
set -euo pipefail

# --- config ---
MODEL="${MODEL:-$HOME/piper_en/en/en_US/amy/medium/en_US-amy-medium.onnx}"
CONF="${CONF:-$HOME/piper_en/en/en_US/amy/medium/en_US-amy-medium.onnx.json}"
OUT="${OUT:-assets/voiceover_48k_loudnorm.wav}"
TEXT="${TEXT:-}"          # inline 텍스트
TEXT_FILE="${TEXT_FILE:-}" # 파일 입력

mkdir -p "$(dirname "$OUT")"

# 1) TTS → 원본 wav
RAW="$(dirname "$OUT")/.tmp_vo_raw.wav"
if [[ -n "$TEXT_FILE" ]]; then
  piper --model "$MODEL" --config "$CONF" --output_file "$RAW" --file "$TEXT_FILE" \
        --length_scale 1.0 --noise_scale 0.5 --noise_w 0.7
elif [[ -n "$TEXT" ]]; then
  piper --model "$MODEL" --config "$CONF" --output_file "$RAW" \
        --length_scale 1.0 --noise_scale 0.5 --noise_w 0.7 \
        --text "$TEXT"
else
  echo "ERROR: provide TEXT=... or TEXT_FILE=path" >&2; exit 1
fi

# 2) 48k 스테레오 변환
MID="$(dirname "$OUT")/.tmp_vo_48k.wav"
ffmpeg -y -hide_banner -loglevel error -i "$RAW" -ar 48000 -ac 2 "$MID"

# 3) loudnorm 두-패스
export STATS_RAW="$(dirname "$OUT")/.loudnorm_stats_raw.txt"
export STATS_JSON="$(dirname "$OUT")/.loudnorm_stats.json"

ffmpeg -y -hide_banner -loglevel info -i "$MID" \
  -af loudnorm=I=-16:LRA=7:TP=-1.5:print_format=json \
  -f null - 2> "$STATS_RAW"

python - <<'PY'
import re, json, sys, os
raw = open(os.environ['STATS_RAW'],'r',errors='ignore').read()
m = re.search(r'\{\s*"input_i".*?\}', raw, flags=re.S)
if not m:
    sys.exit("ERROR: JSON block not found. Check stats raw log.")
open(os.environ['STATS_JSON'],'w').write(m.group(0))
PY

FILTER="$(python - <<'PY'
import json, os
d=json.load(open(os.environ['STATS_JSON']))
print(
  "loudnorm=I=-16:LRA=7:TP=-1.5:"
  f"measured_I={d['input_i']}:"
  f"measured_LRA={d['input_lra']}:"
  f"measured_TP={d['input_tp']}:"
  f"measured_thresh={d['input_thresh']}:"
  f"offset={d['target_offset']}:"
  "linear=true"
)
PY
)"

ffmpeg -y -hide_banner -loglevel error -i "$MID" -af "$FILTER" -ar 48000 -ac 2 "$OUT"

# 4) 청소
rm -f "$RAW" "$MID" "$STATS_RAW" "$STATS_JSON"
echo "[OK] wrote: $OUT"
