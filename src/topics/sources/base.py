from dataclasses import dataclass
from typing import List, Dict, Any

@dataclass
class Candidate:
    title: str
    category: str
    signals: Dict[str, float]
    terms: List[str]
    source: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "category": self.category,
            "signals": self.signals,
            "terms": self.terms,
            "source": self.source,
        }
