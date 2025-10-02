import argparse, json, yaml, pathlib, datetime as dt
from .scorer import base_score, jaccard_sim
from .diversify import History
from . import bandit

def pass_constraints(c, cfg, hist: History, today):
    cats = cfg['categories']
    cons = cfg.get('constraints', {})
    cat = c['category']
    # cooldown
    cooldown = cats.get(cat,{}).get('cooldown_days', 0)
    for r in hist.recent(days=cooldown, today=today):
        if r['category']==cat:
            return False
    # weekly quota
    maxw = cats.get(cat,{}).get('max_weekly', 99)
    if hist.count_weekly(cat, today) >= maxw:
        return False
    # similarity to recent
    recents = hist.recent(days=cons.get('recent_days_for_similarity',14), today=today)
    th = cons.get('similarity_threshold', 0.8)
    for r in recents:
        if jaccard_sim(c['title'], r['title']) >= th:
            return False
    # banned terms
    for b in cfg.get('banned_terms', []):
        if b in c['title']:
            return False
    return True

parser = argparse.ArgumentParser()
parser.add_argument('--topics', required=True)  # topics.yml
parser.add_argument('--constraints', required=True)  # constraints.yml
parser.add_argument('--history', required=True)
parser.add_argument('--bandit', required=True)
parser.add_argument('--candidates', required=False)  # optional prebuilt
parser.add_argument('--out', required=True)
parser.add_argument('--target', type=int, default=None)


def main():
    args = parser.parse_args()
    tcfg = yaml.safe_load(open(args.topics, 'r', encoding='utf-8'))
    cons = yaml.safe_load(open(args.constraints, 'r', encoding='utf-8'))
    cfg = {**tcfg, **cons}
    hist_path = pathlib.Path(args.history)
    if hist_path.exists():
        rows = [json.loads(l) for l in hist_path.read_text(encoding='utf-8').splitlines() if l.strip()]
    else:
        rows = []
    hist = History(rows)

    # load candidates
    if args.candidates:
        cands = [json.loads(l) for l in pathlib.Path(args.candidates).read_text(encoding='utf-8').splitlines() if l.strip()]
    else:
        # fallback to run_all default
        tmp = pathlib.Path('data')/f'candidates_{dt.datetime.now().strftime("%H%M%S")}.jsonl'
        import subprocess
        subprocess.check_call(['python','-m','src.topics.sources.run_all','--config','configs/sources.yml','--out',str(tmp)])
        cands = [json.loads(l) for l in tmp.read_text(encoding='utf-8').splitlines() if l.strip()]

    # score
    bstate = bandit.load_state(args.bandit)
    for c in cands:
        c['base'] = base_score(c.get('signals',{}))
        c['final'] = c['base'] + bandit.boost(c['category'], bstate)

    cands.sort(key=lambda x: -x['final'])

    today = dt.date.today()
    target = args.target or tcfg.get('target_daily', 5)
    picked = []
    for c in cands:
        if pass_constraints(c, cfg, hist, today):
            picked.append(c)
        if len(picked) >= target:
            break

    outp = pathlib.Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in picked), encoding='utf-8')

if __name__ == '__main__':
    main()
