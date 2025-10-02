#!/usr/bin/env python3
import argparse, os, re, subprocess, tempfile
from datetime import timedelta
from pydub import AudioSegment

TIME_RE = re.compile(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)")

def parse_srt(text: str):
    blocks = re.split(r"\r?\n\r?\n", text.strip())
    for b in blocks:
        lines = [ln.strip("\ufeff") for ln in b.strip().splitlines()]
        if not lines:
            continue
        # 0번 라인이 번호일 수도, 바로 타임라인일 수도
        line_idx = 1 if (len(lines) >= 2 and TIME_RE.search(lines[1])) else 0
        m = TIME_RE.search(lines[line_idx]) if line_idx < len(lines) else None
        if not m:
            continue
        h1,m1,s1,ms1,h2,m2,s2,ms2 = map(int, m.groups())
        start = timedelta(hours=h1, minutes=m1, seconds=s1, milliseconds=ms1)
        end   = timedelta(hours=h2, minutes=m2, seconds=s2, milliseconds=ms2)
        content = " ".join([ln.strip() for ln in lines[line_idx+1:] if ln.strip()])
        yield {"start": start, "end": end, "text": content}

def synth_piper(text, model_path, out_path, length_scale=1.0, noise_scale=0.33, noise_w=0.5):
    cmd = [
        "piper", "-m", model_path,
        "--length_scale", str(length_scale),
        "--noise_scale", str(noise_scale),
        "--noise_w", str(noise_w),
        "-f", out_path
    ]
    p = subprocess.run(cmd, input=text.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(f"Piper 합성 실패: {p.stderr.decode(errors='ignore')}")

def td_ms(td): return int(td.total_seconds() * 1000)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--srt", required=True)
    ap.add_argument("--out", required=True)  # .wav
    ap.add_argument("--piper-model", default=None, help="Piper .onnx 경로 (미지정 시 ~/piper 첫 모델 사용)")
    ap.add_argument("--length-scale", type=float, default=1.0)
    ap.add_argument("--noise-scale", type=float, default=0.33)
    ap.add_argument("--noise-w",     type=float, default=0.5)
    ap.add_argument("--gain-db",     type=float, default=0.0)
    args = ap.parse_args()

    model = args.piper_model
    if not model:
        home = os.path.expanduser("~/piper")
        if os.path.isdir(home):
            cands = [os.path.join(home, f) for f in os.listdir(home) if f.endswith(".onnx")]
            if cands:
                model = sorted(cands)[0]
    if not model or not os.path.isfile(model):
        raise SystemExit("❌ Piper .onnx 모델이 필요합니다. (--piper-model 지정 또는 ~/piper/*.onnx 배치)")

    with open(args.srt, encoding="utf-8") as f:
        items = list(parse_srt(f.read()))
    if not items:
        raise SystemExit("❌ SRT에서 자막 항목을 찾지 못했습니다.")

    total_ms = td_ms(max(i["end"] for i in items)) + 1000
    master = AudioSegment.silent(duration=total_ms)

    with tempfile.TemporaryDirectory() as td:
        for idx, it in enumerate(items, 1):
            text = it["text"].strip()
            if not text:
                continue
            seg_wav = os.path.join(td, f"seg_{idx:04d}.wav")
            synth_piper(text, model, seg_wav, args.length_scale, args.noise_scale, args.noise_w)
            seg = AudioSegment.from_file(seg_wav)
            start_ms = td_ms(it["start"]); end_ms = td_ms(it["end"])
            target = max(50, end_ms - start_ms)
            # 길이 맞추기(간단): 길면 컷, 짧으면 무음 패드
            if len(seg) > target:
                seg = seg[:target]
            elif len(seg) < target:
                seg = seg + AudioSegment.silent(duration=(target - len(seg)))
            master = master.overlay(seg, position=start_ms)

    if args.gain_db:
        master += args.gain_db

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    master.export(args.out, format="wav")
    print(f"✅ VO 작성 완료 → {args.out}")

if __name__ == "__main__":
    main()
