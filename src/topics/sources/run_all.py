import argparse, yaml, subprocess, json, pathlib, tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--config', required=True)
parser.add_argument('--out', required=True)

def main():
    args = parser.parse_args()
    cfg = yaml.safe_load(open(args.config, 'r', encoding='utf-8'))
    out_dir = pathlib.Path(args.out).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    merged = []
    for i, s in enumerate(cfg['sources']):
        name = s['name']
        a = s.get('args', {})
        tmp = pathlib.Path(tempfile.gettempdir())/f"cands_{i}.jsonl"
        if name == 'seed_list':
            cmd = ['python','-m','src.topics.sources.seed_list','--file',a['file'],'--category',a['category'],'--out',str(tmp)]
        elif name == 'youtube_suggest':
            cmd = ['python','-m','src.topics.sources.youtube_suggest','--queries',*a['queries'],'--category_map',json.dumps(a.get('category_map',{})),'--out',str(tmp)]
        else:
            continue
        subprocess.check_call(cmd)
        merged.extend([json.loads(l) for l in tmp.read_text(encoding='utf-8').splitlines() if l.strip()])
    pathlib.Path(args.out).write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in merged), encoding='utf-8')

if __name__ == '__main__':
    main()
