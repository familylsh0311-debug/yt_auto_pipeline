#!/usr/bin/env bash
set -euo pipefail

# 1) venv / 의존성
if [ ! -d "$HOME/.venv/topic" ]; then
  python3 -m venv "$HOME/.venv/topic"
fi
source "$HOME/.venv/topic/bin/activate"
python -m pip install -U pip
python -m pip install -r requirements-topic-engine.txt

# 2) 패키지 인식(__init__.py) 보강
find src -type d -not -path '*/\.*' -exec bash -lc 'for d in "$@"; do [ -f "$d/__init__.py" ] || : > "$d/__init__.py"; done' _ {} +

# 3) rapidfuzz 없이 동작하도록 scorer/bandit 패치
cat > src/topics/scorer.py <<'PY'
from typing import Dict
def base_score(signals: Dict[str, float]) -> float:
    return 0.45*signals.get('trend',0) + 0.35*signals.get('search',0) + 0.20*signals.get('freshness',0)
def jaccard_sim(a: str, b: str) -> float:
    A = set(a.lower().split()); B = set(b.lower().split())
    if not A and not B: return 1.0
    return len(A & B) / max(1, len(A | B))
PY

cat > src/topics/bandit.py <<'PY'
import json, pathlib, random
def load_state(path: str):
    p = pathlib.Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {}
def save_state(path: str, state):
    pathlib.Path(path).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
def boost(category: str, state: dict) -> float:
    ab = state.get(category, {"alpha":1, "beta":1})
    return 0.1 * (random.betavariate(ab['alpha'], ab['beta']) - 0.5)
PY

# 4) 네트워크 의존성 없는 seeds 전용 소스 설정
mkdir -p configs out/queue data/manifests manifests
cat > configs/sources.seeds.yml <<'YML'
sources:
  - name: seed_list
    args: { file: data/seeds/evergreen_ko.txt,    category: ai.tools }
  - name: seed_list
    args: { file: data/seeds/blue_archive_ko.txt, category: games.blue_archive }
YML

# 5) bandit 상태 초기화(비어있으면)
[ -s data/bandit_state.json ] || printf '{}' > data/bandit_state.json

# 6) 후보 생성(시드) → 주제 선택 → 배치 실행
python -m src.topics.sources.run_all --config configs/sources.seeds.yml --out data/candidates.jsonl
echo "[OK] candidates:" $(wc -l < data/candidates.jsonl)

python -m src.topics.daily \
  --topics configs/topics.yml \
  --constraints configs/constraints.yml \
  --history data/topic_history.csv \
  --bandit data/bandit_state.json \
  --candidates data/candidates.jsonl \
  --out out/queue/topic_queue.jsonl --target 5
echo "[OK] picked:" $(wc -l < out/queue/topic_queue.jsonl)

python -m src.pipeline.batch --queue out/queue/topic_queue.jsonl --max 5

echo "[LIST] manifests/"
ls -la manifests | head -n 20
echo "[LIST] data/manifests/"
ls -la data/manifests | head -n 20

echo "NOTE: 현재는 스텁이라 mp4 합성은 안 합니다. manifest/샷/프롬프트 파일이 생성되면 정상입니다."
