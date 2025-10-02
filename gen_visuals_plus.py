#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SRT → (txt2img) → shot.png → (img2vid or Ken Burns) shot.mp4 → concat → all_video.mp4 → (옵션: 오디오 mux)
- AUTOMATIC1111 WebUI가 켜져있으면 이미지 생성, 아니면 기존 PNG 사용
- --t2v svd: Stable Video Diffusion(img2vid)로 모션 생성 (없으면 폴백)
- 1080x1920, 30fps
"""
import os, sys, json, subprocess, re, time
from pathlib import Path

def sh(cmd):
    print(cmd)
    subprocess.run(cmd, shell=True, check=True)

def t2s(t):
    h,m,sms = t.split(':',2)
    if ',' in sms:
        s,ms = sms.split(',',1)
    else:
        s,ms = sms,'0'
    return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000.0

def parse_srt(srt_path):
    s = Path(srt_path).read_text(encoding='utf-8')
    pat = re.compile(
        r'^\s*(\d+)\s*\n'
        r'\s*([0-9:,]+)\s*-->\s*([0-9:,]+)\s*\n'
        r'((?:.+\n?)*?)'
        r'(?=\n\s*\d+\s*\n|\Z)', re.M)
    blocks=[]
    for num, st, ed, body in pat.findall(s):
        text = re.sub(r'<[^>]+>','', body).strip().replace('\n',' ')
        dur = max(0.5, t2s(ed)-t2s(st))
        blocks.append(dict(idx=int(num), text=text, start=st, end=ed, dur=dur))
    return blocks

def sd_txt2img(a1111_url, prompt, neg, w, h, steps, cfg, seed, out_png):
    import requests, base64
    payload = {
        "prompt": prompt,
        "negative_prompt": neg,
        "steps": steps,
        "cfg_scale": cfg,
        "seed": seed,
        "width": w, "height": h,
        "sampler_name": "DPM++ 2M Karras",
        "batch_size": 1,
    }
    try:
        r = requests.post(f"{a1111_url}/sdapi/v1/txt2img", json=payload, timeout=300)
        r.raise_for_status()
        img64 = r.json()["images"][0]
        Path(out_png).parent.mkdir(parents=True, exist_ok=True)
        with open(out_png, "wb") as f:
            f.write(base64.b64decode(img64.split(",",1)[-1]))
        return True
    except Exception as e:
        print(f"[SD] txt2img 실패, 폴백: {e}")
        return False

def make_kenburns(png, mp4, d, fps, w, h, encoder):
    frames = max(1, int(d*fps + 0.5))
    # nvenc면 p5, 아니면 libx264의 veryfast (이전 오류 원인 해결)
    preset = "p5" if "nvenc" in encoder else "veryfast"
    gop = "-g 60 -keyint_min 60" if "nvenc" in encoder else "-x264-params keyint=60:min-keyint=60:scenecut=0"
    sh(
        f'ffmpeg -y -loop 1 -t "{d:.3f}" -i "{png}" '
        f'-filter_complex "zoompan=z=\'min(zoom+0.0008,1.15)\':d={frames}:x=\'iw/2-(iw/zoom/2)\':y=\'ih/2-(ih/zoom/2)\',scale={w}:{h},fps={fps},format=yuv420p" '
        f'-frames:v {frames} -c:v {encoder} -preset {preset} {gop} -pix_fmt yuv420p -movflags +faststart "{mp4}"'
    )

def try_svd(img_path, mp4_out, d, fps, w, h, encoder):
    """Stable Video Diffusion (img2vid) → mp4. 실패 시 False 반환."""
    try:
        import torch
        from PIL import Image
        from diffusers import StableVideoDiffusionPipeline
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device != "cuda":
            print("[SVD] CUDA GPU가 필요합니다 → 폴백(Ken Burns)."); return False

        hf_token = os.getenv("HF_TOKEN", None)
        pipe = StableVideoDiffusionPipeline.from_pretrained(
            "stabilityai/stable-video-diffusion-img2vid-xt-1-1",
            torch_dtype=torch.float16, use_safetensors=True, variant="fp16",
            token=hf_token
        ).to(device)
        pipe.enable_model_cpu_offload()

        img = Image.open(img_path).convert("RGB").resize((w, h), Image.LANCZOS)

        target_frames = max(12, min(72, int(d*fps)))

        video_frames = pipe(img, decode_chunk_size=8, num_frames=target_frames).frames[0]

        import cv2
        tmp = Path(mp4_out).with_suffix(".raw.mp4")
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        vw = cv2.VideoWriter(str(tmp), fourcc, fps, (w, h))
        for f in video_frames:
            fr = cv2.cvtColor(f, cv2.COLOR_RGB2BGR)
            vw.write(fr)
        vw.release()

        preset = "p5" if "nvenc" in encoder else "veryfast"
        gop = "-g 60 -keyint_min 60" if "nvenc" in encoder else "-x264-params keyint=60:min-keyint=60:scenecut=0"

        def getdur(p):
            r = subprocess.run(f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{p}"',
                               shell=True, capture_output=True, text=True)
            return float((r.stdout or "0").strip() or 0)
        cur = getdur(tmp)
        if cur <= 0:
            print("[SVD] 생성 영상 길이 확인 실패 → 폴백."); return False

        if cur < d - 0.03:
            pad = d - cur
            sh(f'ffmpeg -y -i "{tmp}" -vf "tpad=stop_mode=clone:stop_duration={pad:.3f},fps={fps},scale={w}:{h},format=yuv420p" '
               f'-c:v {encoder} -preset {preset} {gop} -pix_fmt yuv420p -movflags +faststart "{mp4_out}"')
        elif cur > d + 0.03:
            sh(f'ffmpeg -y -ss 0 -t {d:.3f} -i "{tmp}" -vf "fps={fps},scale={w}:{h},format=yuv420p" '
               f'-c:v {encoder} -preset {preset} {gop} -pix_fmt yuv420p -movflags +faststart "{mp4_out}"')
        else:
            sh(f'ffmpeg -y -i "{tmp}" -vf "fps={fps},scale={w}:{h},format=yuv420p" '
               f'-c:v {encoder} -preset {preset} {gop} -pix_fmt yuv420p -movflags +faststart "{mp4_out}"')

        try: Path(tmp).unlink(missing_ok=True)
        except: pass
        return True
    except Exception as e:
        print(f"[SVD] 실패 → 폴백(Ken Burns). 이유: {e}")
        return False

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--srt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--size", default="1080x1920")
    ap.add_argument("--style", default="")
    ap.add_argument("--neg", default="lowres, blurry, watermark, text, caption, logo")
    ap.add_argument("--steps", type=int, default=28)
    ap.add_argument("--cfg", type=float, default=6.5)
    ap.add_argument("--seed", type=int, default=-1)
    ap.add_argument("--sd-url", default="http://127.0.0.1:7860")
    ap.add_argument("--t2v", choices=["off","svd"], default="svd")
    ap.add_argument("--encoder", default=("h264_nvenc" if os.getenv("YT_ENCODER")=="nvenc" else "libx264"))
    args = ap.parse_args()

    w,h = map(int, args.size.lower().split('x',1))
    outdir = Path(args.out)
    (outdir/"video").mkdir(parents=True, exist_ok=True)

    blocks = parse_srt(args.srt)
    (outdir/"durations.txt").write_text("\n".join(f"{b['dur']:.3f}" for b in blocks), encoding="utf-8")
    print(f"▶ durations.txt 저장 ({len(blocks)}줄)")

    # txt2img (AUTOMATIC1111 있으면 사용)
    a1111_ok = False
    try:
        import requests
        requests.get(args.sd_url, timeout=2)
        a1111_ok = True
    except Exception:
        print("ℹ️ AUTOMATIC1111 미동작: 이미지 생성은 건너뜁니다(기존 PNG 사용).")

    for i,b in enumerate(blocks):
        seg = outdir/f"video/seg_{i:03d}"
        seg.mkdir(parents=True, exist_ok=True)
        png = seg/"shot.png"
        if a1111_ok:
            prompt = f"{b['text']}, {args.style}".strip(", ")
            made = sd_txt2img(args.sd_url, prompt, args.neg, w, h, args.steps, args.cfg, args.seed, str(png))
            print(f"↪ seg_{i:03d} {'생성완료' if made else '생성실패→기존PNG'}")
        else:
            print(f"↪ seg_{i:03d} 기존 PNG 사용")

    # img2vid or Ken Burns
    print("▶ 이미지 → shot.mp4")
    for i,b in enumerate(blocks):
        seg = outdir/f"video/seg_{i:03d}"
        png = seg/"shot.png"
        mp4 = seg/"shot.mp4"
        if not png.exists():
            print(f"⚠️ PNG 없음: {png} → 건너뜀"); continue
        ok=False
        if args.t2v=="svd":
            ok = try_svd(str(png), str(mp4), b["dur"], args.fps, w, h, args.encoder)
        if not ok:
            make_kenburns(str(png), str(mp4), b["dur"], args.fps, w, h, args.encoder)

    # concat
    concat_list = outdir/"all_video.mp4.list.txt"
    with open(concat_list,"w",encoding="utf-8") as f:
        for i,_ in enumerate(blocks):
            f.write(f"file 'video/seg_{i:03d}/shot.mp4'\n")

    allv = outdir/"all_video.mp4"
    sh(f'ffmpeg -y -f concat -safe 0 -i "{concat_list}" -c copy "{allv}"')

    # 오디오 자동 mux
    alla = outdir/"all_audio.m4a"
    if Path(alla).exists():
        final = outdir/"final.mp4"
        sh(f'ffmpeg -y -i "{allv}" -i "{alla}" -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k -shortest "{final}"')
        print(f"✅ 최종: {final}")
    else:
        print(f"✅ 영상만 생성: {allv} (오디오는 all_audio.m4a가 있으면 자동 합쳐집니다)')

if __name__ == "__main__":
    main()
