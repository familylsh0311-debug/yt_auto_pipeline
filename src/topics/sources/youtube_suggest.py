# Lightweight YouTube suggest (no API). May throttle; keep queries small.
import argparse, json, time
import requests
from .base import Candidate

parser = argparse.ArgumentParser()
parser.add_argument('--queries', nargs='+', required=True)
parser.add_argument('--category_map', type=json.loads, default='{}')
parser.add_argument('--out', required=True)

def fetch_suggest(q):
    # Public suggest endpoint (client=firefox works often)
    url = 'https://suggestqueries.google.com/complete/search'
    params = {"client":"firefox", "ds":"yt", "q": q}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    return data[1] if isinstance(data, list) and len(data)>=2 else []

def main():
    args = parser.parse_args()
    cmap = json.loads(args.category_map) if isinstance(args.category_map, str) else args.category_map
    out = open(args.out, 'w', encoding='utf-8')
    try:
        for q in args.queries:
            try:
                sugs = fetch_suggest(q)
            except Exception:
                sugs = []
            cat = cmap.get(q, 'internet.culture')
            for s in sugs[:8]:
                c = Candidate(title=s, category=cat,
                              signals={"trend":0.6, "search":0.7, "freshness":0.6},
                              terms=list({q, *s.split()}), source='youtube_suggest')
                out.write(json.dumps(c.to_json(), ensure_ascii=False) + '\n')
            time.sleep(0.5)
    finally:
        out.close()

if __name__ == '__main__':
    main()
