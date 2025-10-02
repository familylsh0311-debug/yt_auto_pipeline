import argparse, json, pathlib
parser = argparse.ArgumentParser()
parser.add_argument('--in', dest='inp', required=True)
parser.add_argument('--outdir', required=True)

def main():
    args = parser.parse_args()
    outdir = pathlib.Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for i, line in enumerate(pathlib.Path(args.inp).read_text(encoding='utf-8').splitlines()):
        if not line.strip(): continue
        j = json.loads(line)
        brief = {
            "id": f"topic_{i:03d}",
            "title": j['title'],
            "category": j['category'],
            "angle": "한 문장으로 요점만 강하게",
            "terms": j.get('terms', [])
        }
        (outdir/f"{brief['id']}.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding='utf-8')

if __name__ == '__main__':
    main()
