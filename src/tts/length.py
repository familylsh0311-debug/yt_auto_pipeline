# Stub: estimate length from char count; replace with audio duration.
import argparse, csv, pathlib
parser = argparse.ArgumentParser()
parser.add_argument('--beats', required=True)
parser.add_argument('--write', required=True)

def main():
    import math
    args = parser.parse_args()
    rows = list(csv.DictReader(open(args.beats, encoding='utf-8')))
    for r in rows:
        chars = len(r['line_ko'])
        est = max(1.5, min(8.0, chars/10.0))  # ~10cps heuristic
        r['sec_target'] = f"{est:.2f}"
    # rewrite
    import io
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=rows[0].keys())
    w.writeheader(); w.writerows(rows)
    pathlib.Path(args.write).write_text(out.getvalue(), encoding='utf-8')

if __name__ == '__main__':
    main()
