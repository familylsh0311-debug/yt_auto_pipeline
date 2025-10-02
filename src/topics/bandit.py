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
