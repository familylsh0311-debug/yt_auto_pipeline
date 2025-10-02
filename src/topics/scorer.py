from typing import Dict
def base_score(signals: Dict[str, float]) -> float:
    return 0.45*signals.get('trend',0) + 0.35*signals.get('search',0) + 0.20*signals.get('freshness',0)
def jaccard_sim(a: str, b: str) -> float:
    A = set(a.lower().split()); B = set(b.lower().split())
    if not A and not B: return 1.0
    return len(A & B) / max(1, len(A | B))
