import argparse, csv, subprocess, pathlib, shlex
parser=argparse.ArgumentParser()
parser.add_argument('--beats', required=True)
parser.add_argument('--outdir', required=True)
parser.add_argument('--voice', default='ko+f3')  # 남/여 조절: ko+f3, ko+m3 등
parser.add_argument('--wpm', type=int, default=170)
def main():
    a=parser.parse_args(); out=pathlib.Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    for row in csv.DictReader(open(a.beats, encoding='utf-8')):
        text=row['line_ko'].replace('"','\\"')
        wav=out/f"beat_{row['beat_id']}.wav"
        cmd=f'espeak-ng -v {shlex.quote(a.voice)} -s {a.wpm} -p 40 -a 170 -w {shlex.quote(str(wav))} "{text}"'
        subprocess.check_call(cmd, shell=True)
    print('[tts] wrote to', out)
if __name__=='__main__': main()
