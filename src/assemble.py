import os
from typing import List, Dict, Any
from .utils.ffmpeg import run as ff, probe_duration

def write_srt(segments: List[Dict[str, Any]], out_path: str):
    def fmt(t):
        h = int(t//3600); m=int((t%3600)//60); s=t%60
        return f"{h:02d}:{m:02d}:{int(s):02d},{int((s-int(s))*1000):03d}"
    t = 0.0
    with open(out_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = t
            end = t + seg["dur"]
            f.write(f"{i}\n{fmt(start)} --> {fmt(end)}\n{seg['text']}\n\n")
            t = end

def concat_videos(video_paths: List[str], out_path: str):
    list_path = out_path + ".list.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for vp in video_paths:
            ap = os.path.abspath(vp).replace("'", "'\\''")
            f.write(f"file '{ap}'\n")
    ff(f'ffmpeg -y -f concat -safe 0 -i "{list_path}" -c copy "{out_path}"')

def mix_audio(audio_paths: List[str], out_path: str):
    list_path = out_path + ".alist.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for ap in audio_paths:
            ab = os.path.abspath(ap).replace("'", "'\\''")
            f.write(f"file '{ab}'\n")
    ff(f'ffmpeg -y -f concat -safe 0 -i "{list_path}" -c:a aac -b:a 192k "{out_path}"')

def mux_av(video_path: str, audio_path: str, out_path: str):
    # faststart + BT.709 + 48kHz
    ff(f'ffmpeg -y -i "{video_path}" -i "{audio_path}" '
       f'-map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k -ar 48000 -shortest '
       f'-movflags +faststart -colorspace bt709 -color_primaries bt709 -color_trc bt709 "{out_path}"')

def overlay_music(audio_path: str, music_path: str, out_path: str, music_db=-18):
    vol = 10**(music_db/20)
    ff(f'ffmpeg -y -i "{audio_path}" -i "{music_path}" '
       f'-filter_complex "[1:a]volume={vol}[bg];[0:a][bg]amix=inputs=2:duration=shortest:dropout_transition=2" '
       f'-c:a aac -b:a 192k "{out_path}"')

def write_metadata(out_dir: str, lang: str, title: str, desc: str, hashtags: List[str], pinned: str=""):
    meta = os.path.join(out_dir, "meta")
    os.makedirs(meta, exist_ok=True)
    def w(name, content):
        with open(os.path.join(meta, f"{lang}.{name}.txt"), "w", encoding="utf-8") as f:
            f.write((content or "").strip()+"\n")
    w("title", title)
    w("desc", desc)
    w("hashtags", " ".join(f"#{h}" for h in hashtags))
    w("pinned", pinned or "시청해 주셔서 감사합니다! 🙌")

# 옵션: -14 LUFS 정규화(있으면 사용)
def normalize_audio(input_a: str, out_path: str, i=-14, tp=-1.0, lra=11.0):
    import subprocess, json
    # 첫 패스: 측정
    p1 = subprocess.run(['ffmpeg','-nostdin','-y','-i',input_a,'-filter_complex',
                         f'loudnorm=I={i}:TP={tp}:LRA={lra}:print_format=json',
                         '-f','null','-'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    jtxt = ''
    for line in p1.stderr.splitlines():
        if line.strip().startswith('{') and '"input_i"' in line: jtxt = line.strip()
    meas = {}
    if jtxt:
        try: meas = json.loads(jtxt)
        except: pass
    if meas:
        flt = ('loudnorm=I=%s:TP=%s:LRA=%s:measured_I=%s:measured_LRA=%s:measured_TP=%s:measured_thresh=%s:linear=true'
               %(i,tp,lra,meas.get("input_i",-23),meas.get("input_lra",7),meas.get("input_tp",-2),meas.get("input_thresh",-34)))
    else:
        flt = f'loudnorm=I={i}:TP={tp}:LRA={lra}'
    ff(f'ffmpeg -y -i "{input_a}" -filter:a "{flt}" -c:a aac -b:a 192k "{out_path}"')
