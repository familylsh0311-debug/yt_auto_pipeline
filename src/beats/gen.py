# Simple beat generator: 3 beats (hook/body/cta)
import argparse, json, csv, pathlib
parser = argparse.ArgumentParser()
parser.add_argument('--brief', required=True)
parser.add_argument('--out', required=True)

def main():
    args = parser.parse_args()
    brief = json.loads(pathlib.Path(args.brief).read_text(encoding='utf-8'))
    rows = [
        {"beat_id":1, "intent":"hook", "line_ko": f"{brief['title']} — 핵심만 30초!", "sec_target":3, "visual_hint":"타이포 급줌", "sfx_hint":"whoosh", "brand_safe":"ok"},
        {"beat_id":2, "intent":"body", "line_ko": f"요점 2가지만: ① ②", "sec_target":24, "visual_hint":"아이콘/픽토그램", "sfx_hint":"pop", "brand_safe":"ok"},
        {"beat_id":3, "intent":"cta", "line_ko": "저장해두면 나중에 도움!", "sec_target":3, "visual_hint":"하이라이트 카드", "sfx_hint":"ding", "brand_safe":"ok"},
    ]
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader(); w.writerows(rows)

if __name__ == '__main__':
    main()
