import argparse, pathlib, json
from .base import Candidate

parser = argparse.ArgumentParser()
parser.add_argument('--file', required=True)
parser.add_argument('--category', required=True)
parser.add_argument('--out', required=True)

def main():
    args = parser.parse_args()
    p = pathlib.Path(args.file)
    lines = [l.strip() for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', encoding='utf-8') as f:
        for t in lines:
            c = Candidate(title=t, category=args.category,
                          signals={"trend":0.3, "search":0.4, "freshness":0.5},
                          terms=t.split(), source='seed_list')
            f.write(json.dumps(c.to_json(), ensure_ascii=False) + '\n')

if __name__ == '__main__':
    main()
