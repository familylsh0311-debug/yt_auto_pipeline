# Very small planner to produce shots.tsv and prompts.jsonl
import argparse, csv, json, pathlib
parser = argparse.ArgumentParser()
parser.add_argument('--beats', required=True)
parser.add_argument('--out_tsv', required=True)
parser.add_argument('--out_prompts', required=True)

def main():
    args = parser.parse_args()
    beats = list(csv.DictReader(open(args.beats, encoding='utf-8')))
    tsv_lines = []
    prompts = []
    for b in beats:
        bid = int(b['beat_id'])
        # shot 1: title/typo card
        tsv_lines.append([bid, 1, 'img', 'SDXL: high contrast title card', 1.2, '-'])
        prompts.append({"shot_id": f"{bid}-1", "engine":"sdxl", "seed": 1234, "cfg": 6.5, "steps": 30, "prompt": "neon title, high contrast", "neg":"blurry"})
        # shot 2: motion/b-roll placeholder
        tsv_lines.append([bid, 2, 'motion', 'AnimateDiff: fast zoom / icon pop', float(b.get('sec_target', 3)) - 1.2, '-'])
    # write
    out_tsv = pathlib.Path(args.out_tsv)
    out_prom = pathlib.Path(args.out_prompts)
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    with out_tsv.open('w', encoding='utf-8') as f:
        f.write('beat_id\tshot_id\ttype\tprompt/motion\tduration_est\tsrc\n')
        for r in tsv_lines:
            f.write('\t'.join(map(str,r))+'\n')
    out_prom.write_text('\n'.join(json.dumps(p, ensure_ascii=False) for p in prompts), encoding='utf-8')

if __name__ == '__main__':
    main()
