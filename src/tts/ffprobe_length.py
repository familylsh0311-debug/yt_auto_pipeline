import argparse, subprocess, pathlib, csv, io

parser = argparse.ArgumentParser()
parser.add_argument('--beats', required=True)
parser.add_argument('--ttsdir', required=True)

def dur(path):
    s = subprocess.check_output([
        'ffprobe','-v','error',
        '-show_entries','format=duration',
        '-of','default=noprint_wrappers=1:nokey=1',
        path
    ], text=True).strip()
    return max(0.5, float(s))

def main():
    a = parser.parse_args()
    rows = list(csv.DictReader(open(a.beats, encoding='utf-8')))
    for r in rows:
        wav = str(pathlib.Path(a.ttsdir) / f"beat_{r['beat_id']}.wav")
        try:
            r['sec_target'] = f"{dur(wav):.2f}"
        except Exception:
            pass
    s = io.StringIO()
    w = csv.DictWriter(s, fieldnames=rows[0].keys())
    w.writeheader(); w.writerows(rows)
    pathlib.Path(a.beats).write_text(s.getvalue(), encoding='utf-8')

if __name__ == '__main__':
    main()
