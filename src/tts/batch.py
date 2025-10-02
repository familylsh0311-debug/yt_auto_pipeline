# Stub: write per-beat text files; integrate your TTS here.
import argparse, csv, pathlib
parser = argparse.ArgumentParser()
parser.add_argument('--beats', required=True)
parser.add_argument('--outdir', required=True)

def main():
    args = parser.parse_args()
    out = pathlib.Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for b in csv.DictReader(open(args.beats, encoding='utf-8')):
        (out/f"beat_{b['beat_id']}.txt").write_text(b['line_ko'], encoding='utf-8')
        # TODO: replace with real TTS -> beat_{id}.wav

if __name__ == '__main__':
    main()
