import argparse, json, pathlib, subprocess
parser = argparse.ArgumentParser()
parser.add_argument('--queue', required=True)
parser.add_argument('--max', type=int, default=5)
parser.add_argument('--nvenc', action='store_true')


def run_topic(item, i):
    tid = f"t{i:03d}"
    base = pathlib.Path('manifests')/tid
    base.parent.mkdir(parents=True, exist_ok=True)
    brief = base.with_suffix('.brief.json')
    beats = base.with_suffix('.beats.csv')
    shots = base.with_suffix('.shots.tsv')
    prompts = base.with_suffix('.prompts.jsonl')
    outmp4 = pathlib.Path('out')/f"{tid}.mp4"

    # brief
    brief.write_text(json.dumps({"id":tid, "title": item['title'], "category": item['category']}, ensure_ascii=False, indent=2), encoding='utf-8')
    # beats
    subprocess.check_call(['python','-m','src.beats.gen','--brief',str(brief),'--out',str(beats)])
    # tts length (stub)
    subprocess.check_call(['python','-m','src.tts.length','--beats',str(beats),'--write',str(beats)])
    # shots
    subprocess.check_call(['python','-m','src.shots.plan','--beats',str(beats),'--out_tsv',str(shots),'--out_prompts',str(prompts)])
    # compose manifest
    subprocess.check_call(['python','-m','src.render.compose','--topic',item['title'],'--beats',str(beats),'--shots',str(shots),'--prompts',str(prompts),'--out',str(outmp4),'--snap_to_tts'])


def main():
    args = parser.parse_args()
    items = [json.loads(l) for l in pathlib.Path(args.queue).read_text(encoding='utf-8').splitlines() if l.strip()]
    for i, it in enumerate(items[:args.max]):
        run_topic(it, i)

if __name__ == '__main__':
    main()
