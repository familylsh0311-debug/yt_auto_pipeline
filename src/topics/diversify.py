import datetime as dt
from typing import List, Dict, Any

class History:
    def __init__(self, rows: List[Dict[str, Any]]):
        self.rows = rows
    def recent(self, days=14, today=None):
        today = today or dt.date.today()
        res=[]
        for r in self.rows:
            d = dt.date.fromisoformat(r['picked_at'][:10])
            if (today - d).days <= days:
                res.append(r)
        return res
    def count_weekly(self, category, today=None):
        today = today or dt.date.today()
        start = today - dt.timedelta(days=today.weekday())
        end = start + dt.timedelta(days=6)
        c=0
        for r in self.rows:
            d = dt.date.fromisoformat(r['picked_at'][:10])
            if r['category']==category and start<=d<=end:
                c+=1
        return c

