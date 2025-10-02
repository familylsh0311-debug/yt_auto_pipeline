#!/usr/bin/env python3
import argparse, os, re, sys, tempfile, shutil
from datetime import timedelta
from pydub import AudioSegment

TIME_RE = re.compile(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)")

def parse_srt(text:str):
    items=[]
    blocks = re.split(r"\r?\n\r?\n", text.strip())
    for b in blocks:
        lines=b.strip().splitlines()
        if not lines: 
            continue
        # 라인0이 번호일 수도, 바로 타임라인일 수도 있음
        line_idx = 1 if (len(lines)>=2 and TIME_RE.search(lines[1])) else 0
        m = TIME_RE.search(lines[line_idx]) if line_idx < len(lines) else None
        if not m: 
            continue
        h1,m1,s1,ms1,h2,m2,s2,ms2 = map(int, m.groups())
        start = timedelta(hours=h1, minutes=m1, seconds=s1, milliseconds=ms1)
        end   = timedelta(hours=h2, minutes=m2, seconds=s2, milliseconds=ms2)
        content = "\n".join(lines[line_idx+1:]).strip()
        items.append((start,end,content))
    return items

def ms(td): return int(td.total_seconds()*1000)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--srt', required=True, help='input .srt')
    ap.add_argument('--out', required=True, help='output .wav')
    ap.add_argument('--engine', choices=['melo','piper'], default='melo')
    ap.add_argument('--lang', default='kr', help='melo lang: en/jp/zh/kr...')
    ap.add_argument('--melo-speaker', default=None, help='exact melo speaker key')
    ap.add_argument('--melo-speed', type=float, default=1.0)
    ap.add_argument('--piper-model', default=None, help='path to .onnx (piper)')
    ap.add_argument('--gain-db', type=float, default=0.0)
    args = ap.parse_args()

    text = open(args.srt,'r',encoding='utf-8').read()
    subs = parse_srt(text)
    if not subs:
        print('No subtitles found in SRT', file=sys.stderr); sys.exit(1)

    total_ms = ms(subs[-1][1]) + 250
    base = AudioSegment.silent(duration=total_ms)

    tmpdir = tempfile.mkdtemp(prefix='ttsseg_')
    try:
        if args.engine == 'melo':
            from melo.api import TTS
            lang = args.lang.upper()
            lang = 'KR' if lang.startswith('K') else lang
            tts = TTS(language=lang)
            spk2id = tts.hps.data.spk2id
            if args.melo_speaker and args.melo_speaker in spk2id:
                sel = args.melo_speaker
            else:
                sel = next((k for k in spk2id.keys() if k.upper().startswith(lang)), next(iter(spk2id.keys())))
            sid = spk2id[sel]
            print(f'[Melo] language={lang} speaker="{sel}" speed={args.melo_speed}')
            for i, (st, ed, content) in enumerate(subs, 1):
                t = re.sub(r'<[^>]+>', '', content).replace('\n',' ').strip()
                if not t: continue
                outwav = os.path.join(tmpdir, f'{i:04d}.wav')
                tts.tts_to_file(t, speaker_id=sid, speed=args.melo_speed, file_path=outwav)
                seg = AudioSegment.from_file(outwav)
                base = base.overlay(seg, position=ms(st))
        else:
            if not args.piper_model or not os.path.exists(args.piper_model):
                print('Piper requires --piper-model path/to/voice.onnx', file=sys.stderr); sys.exit(2)
            import subprocess
            voice = args.piper_model
            print(f'[Piper] model={voice}')
            for i, (st, ed, content) in enumerate(subs, 1):
                t = re.sub(r'<[^>]+>', '', content).replace('\n',' ').strip()
                if not t: continue
                outwav = os.path.join(tmpdir, f'{i:04d}.wav')
                cmd = ['piper','--model',voice,'--output_file',outwav]
                subprocess.run(cmd, input=t.encode('utf-8'), check=True)
                seg = AudioSegment.from_file(outwav)
                base = base.overlay(seg, position=ms(st))

        if args.gain_db != 0.0:
            base = base.apply_gain(args.gain_db)
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        base.export(args.out, format='wav')
        print(f'✅ VO exported: {args.out} ({len(base)/1000:.2f}s)')
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

if __name__ == '__main__':
    main()
