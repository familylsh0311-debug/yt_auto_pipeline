#!/usr/bin/env bash
set -euo pipefail
source "$HOME/.venv/tts310/bin/activate"

TEXT="${1:-안녕하세요. 스모크 테스트입니다.}"
OUT="${2:-runs/tts/out.wav}"

python - <<'PY' "$TEXT" "$OUT"
import sys
from pathlib import Path
import melo_kr_patch  # ★ 패치 먼저 로드
from melo.api import TTS

text = sys.argv[1]
out  = Path(sys.argv[2])
out.parent.mkdir(parents=True, exist_ok=True)

t = TTS(language="KR", device="cpu")

# 스피커 선택
spk = 0
try:
    spk2id = getattr(getattr(t,"hps").data, "spk2id", {}) or {}
    if isinstance(spk2id, dict) and spk2id:
        spk = spk2id.get("KR") or next(iter(spk2id.values()))
except Exception:
    pass

t.tts_to_file(text, spk, str(out), speed=1.0)
print("[OK] wrote:", out)
PY
