# Stub: only writes manifest.json; hook to your existing ffmpeg/ComfyUI renderer.
import argparse, json, pathlib
parser = argparse.ArgumentParser()
parser.add_argument('--topic', required=True)
parser.add_argument('--beats', required=True)
parser.add_argument('--shots', required=True)
parser.add_argument('--prompts', required=True)
parser.add_argument('--out', required=True)
parser.add_argument('--snap_to_tts', action='store_true')

def main():
    args = parser.parse_args()
    manifest = {
        "topic": args.topic,
        "beats_csv": args.beats,
        "shots_tsv": args.shots,
        "prompts_jsonl": args.prompts,
        "render": args.out,
        "snap_to_tts": bool(args.snap_to_tts),
    }
    mpath = pathlib.Path('data/manifests')/f"{pathlib.Path(args.out).stem}.manifest.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('[compose] manifest written:', mpath)

if __name__ == '__main__':
    main()
