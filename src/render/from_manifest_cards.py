import argparse, json, csv, subprocess, pathlib, tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--manifest', required=True)
parser.add_argument('--out', required=True)
parser.add_argument('--fps', type=int, default=30)
parser.add_argument('--size', default='1080x1920')
parser.add_argument('--bg', default='black')
parser.add_argument('--font', default='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
parser.add_argument('--ttsdir', default=None)  # e.g., out/tts/t000

def ffprobe_dur(path):
    s = subprocess.check_output([
        'ffprobe','-v','error',
        '-show_entries','format=duration',
        '-of','default=noprint_wrappers=1:nokey=1',
        path
    ], text=True).strip()
    return max(0.5, float(s))

def esc(t: str) -> str:
    return t.replace('\\', '\\\\').replace(':', '\\:').replace("'", r"\'")

def make_part(outmp4, dur, text, fps, size, bg, font, audio=None):
    draw = f"drawtext=fontfile='{font}':text='{esc(text[:200])}':x=(w-text_w)/2:y=0.72*h:fontsize=56:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=20:borderw=2:bordercolor=black@0.8"
    if audio:
        subprocess.check_call([
            'ffmpeg','-y',
            '-f','lavfi','-i', f"color=c={bg}:s={size}:d={dur}",
            '-i', audio,
            '-shortest',
            '-vf', draw,
            '-r', str(fps),
            '-pix_fmt','yuv420p',
            '-c:v','libx264','-c:a','aac','-movflags','+faststart',
            outmp4
        ])
    else:
        subprocess.check_call([
            'ffmpeg','-y',
            '-f','lavfi','-i', f"color=c={bg}:s={size}:d={dur}",
            '-vf', draw,
            '-r', str(fps),
            '-pix_fmt','yuv420p',
            '-c:v','libx264','-movflags','+faststart',
            outmp4
        ])

def main():
    a = parser.parse_args()
    man = json.loads(pathlib.Path(a.manifest).read_text(encoding='utf-8'))
    beats = list(csv.DictReader(open(man['beats_csv'], encoding='utf-8')))

    # 기본 TTS 디렉터리 추론: data/manifests/t000.manifest.json -> out/tts/t000
    ttsdir = pathlib.Path(a.ttsdir) if a.ttsdir else pathlib.Path('out/tts') / pathlib.Path(a.manifest).stem.split('.')[0]
    work = pathlib.Path(tempfile.mkdtemp())
    parts = []

    for b in beats:
        txt = b['line_ko']
        audio = ttsdir / f"beat_{b['beat_id']}.wav"
        if audio.exists():
            dur = ffprobe_dur(str(audio))
            audio_path = str(audio)
        else:
            dur = float(b.get('sec_target', 3))
            audio_path = None
        part = work / f"part_{int(b['beat_id']):03d}.mp4"
        make_part(str(part), dur, txt, a.fps, a.size, a.bg, a.font, audio_path)
        parts.append(part)

    listfile = work / 'list.txt'
    listfile.write_text(''.join(f"file '{p.as_posix()}'\n" for p in parts), encoding='utf-8')
    subprocess.check_call(['ffmpeg','-y','-f','concat','-safe','0','-i',str(listfile),'-c','copy',a.out])
    print('[render]', a.out)

if __name__ == '__main__':
    main()
