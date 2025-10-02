#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, subprocess, argparse, time, base64, io, shutil, tempfile
from pathlib import Path

# ---------- 공통 유틸 ----------
def run_cmd(cmd):
    print(f"[CMD] {cmd}")
    cp = subprocess.run(cmd, shell=True)
    if cp.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}")

def enc_args(encoder: str):
    enc = (encoder or "libx264").lower()
    if enc == "h264_nvenc":
        return "-c:v h264_nvenc -preset p5 -rc vbr -b:v 6M -maxrate 8M -profile:v high -pix_fmt yuv420p -movflags +faststart"
    elif enc in ("hevc_nvenc", "h265_nvenc"):
        return "-c:v hevc_nvenc -preset p5 -rc vbr -b:v 6M -maxrate 8M -pix_fmt yuv420p -movflags +faststart"
    else:
        return "-c:v libx264 -preset medium -crf 21 -pix_fmt yuv420p -movflags +faststart"

def parse_srt(path: str):
    txt = Path(path).read_text(encoding="utf-8", errors="ignore")
    blocks = re.split(r"\n\s*\n", txt.strip())
    out = []
    for b in blocks:
        lines = [L.strip("\ufeff").strip() for L in b.splitlines() if L.strip()]
        if not lines: continue
        if re.match(r"^\d+$", lines[0]): lines = lines[1:]
        if not lines: continue
        m = re.match(r"(\d\d:\d\d:\d\d),(\d{3})\s*-->\s*(\d\d:\d\d:\d\d),(\d{3})", lines[0])
        if not m: continue
        def to_sec(hms, ms):
            hh,mm,ss = [int(x) for x in hms.split(":")]
            return hh*3600+mm*60+ss+int(ms)/1000.0
        start = to_sec(m.group(1), m.group(2))
        end   = to_sec(m.group(3), m.group(4))
        text  = " ".join(lines[1:]).strip()
        if end <= start: end = start + 2.0
        out.append({"start":start, "end":end, "text":text})
    return out

def build_prompt(style:str, text:str):
    style = (style or "").strip()
    base = text.strip()
    return f"{style}, {base}" if style else base

# ---------- SD(WebUI) 호출 ----------
def sd_txt2img(sd_url, prompt, negative, w, h, steps, cfg, sampler, seed):
    import requests
    if seed is None or seed < 0:
        seed = int(time.time()*1000) % 4294967295
    payload = {
        "prompt": prompt,
        "negative_prompt": negative or "",
        "steps": int(steps),
        "cfg_scale": float(cfg),
        "width": int(w),
        "height": int(h),
        "sampler_name": sampler or "Euler a",
        "seed": int(seed),
        "restore_faces": False,
        "tiling": False,
        "enable_hr": False,
        "batch_size": 1,
    }
    url = sd_url.rstrip("/") + "/sdapi/v1/txt2img"
    import requests as _r
    r = _r.post(url, json=payload, timeout=600)
    r.raise_for_status()
    data = r.json()
    imgs = data.get("images", [])
    if not imgs:
        raise RuntimeError("SD returned no images")
    b = imgs[0]
    if "," in b:
        b = b.split(",",1)[-1]
    imbytes = base64.b64decode(b)
    from PIL import Image
    img = Image.open(io.BytesIO(imbytes)).convert("RGB")
    return img

# ---------- 비디오 생성(켄 번즈) ----------
def make_kenburns(png, mp4, fps, seconds, w, h, encoder):
    frames = max(1, int(round(fps*seconds)))
    vf = (
        f"zoompan=z='min(zoom+0.0008,1.10)':d={frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',"
        f"scale={w}:{h},fps={fps},format=yuv420p"
    )
    cmd = f'ffmpeg -y -loglevel error -loop 1 -t "{seconds:.3f}" -i "{png}" -filter_complex "{vf}" -frames:v {frames} {enc_args(encoder)} "{mp4}"'
    run_cmd(cmd)

# ---------- SVD 내부 실행(동일 파일을 SVD venv로 재호출) ----------
def call_svd_self_in_venv(svd_py, this_file, png, mp4, fps, seconds, w, h, encoder, model, motion_bucket_id, noise_aug):
    cmd = (
        f'"{svd_py}" "{this_file}" --_svd-internal '
        f'--input "{png}" --output "{mp4}" --fps {fps} --seconds {seconds:.3f} '
        f'--size {w}x{h} --encoder {encoder} '
        f'--svd-model "{model}" --motion-bucket {motion_bucket_id} --noise-aug {noise_aug}'
    )
    run_cmd(cmd)

# ---------- SVD 내부 모드 ----------
def svd_internal(input_png, output_mp4, fps, seconds, size, encoder, model, motion_bucket_id, noise_aug):
    import torch
    from PIL import Image
    from diffusers import StableVideoDiffusionPipeline
    w,h = [int(x) for x in size.lower().split("x")]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype  = torch.float16 if device=="cuda" else torch.float32
    variant = "fp16" if device=="cuda" else None

    pipe = StableVideoDiffusionPipeline.from_pretrained(model, torch_dtype=dtype, variant=variant)
    pipe = pipe.to(device)
    if device == "cpu":
        pipe.enable_model_cpu_offload()

    num_frames = max(8, min(48, int(round(fps*seconds))))
    img = Image.open(input_png).convert("RGB").resize((w,h), Image.LANCZOS)
    out = pipe(
        image=img,
        decode_chunk_size=8,
        num_frames=num_frames,
        motion_bucket_id=int(motion_bucket_id),
        noise_aug_strength=float(noise_aug),
    ).frames[0]

    tmp = Path(tempfile.mkdtemp(prefix="svd_frames_"))
    try:
        for i,fr in enumerate(out):
            fr.save(tmp/f"f_{i:06d}.png")
        cmd = f'ffmpeg -y -loglevel error -r {fps} -i "{tmp}/f_%06d.png" -vf format=yuv420p -frames:v {len(out)} {enc_args(encoder)} "{output_mp4}"'
        run_cmd(cmd)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

# ---------- 메인 ----------
def main():
    ap = argparse.ArgumentParser()
    # 사용자용
    ap.add_argument("--srt", required=False, help="입력 SRT(자막). 컷 타이밍/텍스트 기준")
    ap.add_argument("--out", default="out/shorts_prod", help="출력 폴더")
    ap.add_argument("--sd-url", default="http://127.0.0.1:7860", help="A1111 API URL")
    ap.add_argument("--style", default="", help="스타일 프리셋")
    ap.add_argument("--neg", default="", help="네거티브 프롬프트")
    ap.add_argument("--steps", type=int, default=28)
    ap.add_argument("--cfg", type=float, default=6.5)
    ap.add_argument("--sampler", default="Euler a")
    ap.add_argument("--seed", type=int, default=-1)
    ap.add_argument("--w", type=int, default=1080)
    ap.add_argument("--h", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--max-shot", type=int, default=9999)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--encoder", default="libx264", help="libx264 | h264_nvenc | hevc_nvenc ...")
    ap.add_argument("--t2v", choices=["none","svd"], default="none", help="shot.png -> shot.mp4 생성 방식")
    ap.add_argument("--svd-python", default=str(Path("~/.venv/svd/bin/python").expanduser()))
    ap.add_argument("--svd-model", default=os.environ.get("SVD_MODEL","stabilityai/stable-video-diffusion-img2vid"))
    ap.add_argument("--motion-bucket", type=int, default=127)
    ap.add_argument("--noise-aug", type=float, default=0.1)
    # 내부용(사용자 지정 금지)
    ap.add_argument("--_svd-internal", action="store_true")
    ap.add_argument("--input")
    ap.add_argument("--output")
    ap.add_argument("--seconds", type=float)
    ap.add_argument("--size")
    args = ap.parse_args()

    # 내부(SVD) 모드 진입
    if getattr(args, "_svd_internal", False):
        svd_internal(
            input_png=args.input,
            output_mp4=args.output,
            fps=args.fps,
            seconds=args.seconds,
            size=args.size,
            encoder=args.encoder,
            model=args.svd_model,
            motion_bucket_id=args.motion_bucket,
            noise_aug=args.noise_aug,
        )
        return

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    # 입력이 SRT가 아니면 단일 샷 모드로 동작 (문구 그대로 프롬프트)
    shots = []
    if args.srt and Path(args.srt).exists():
        for i, e in enumerate(parse_srt(args.srt)):
            if i >= args.max_shot: break
            shots.append({
                "idx": i+1,
                "start": e["start"],
                "end": e["end"],
                "seconds": max(0.8, e["end"]-e["start"]),
                "text": e["text"],
            })
    else:
        shots = [{"idx":1, "start":0, "end":2, "seconds":2.0, "text": (args.srt or "A breathtaking cinematic shot")}]

    pngs, mp4s = [], []
    this_file = str(Path(__file__).resolve())

    for s in shots:
        idx = s["idx"]
        d   = float(s["seconds"])
        text= s["text"].strip()
        prompt = build_prompt(args.style, text)

        png = outdir/f"shot_{idx:03d}.png"
        mp4 = outdir/f"shot_{idx:03d}.mp4"

        if args.overwrite or not png.exists():
            img = sd_txt2img(args.sd_url, prompt, args.neg, args.w, args.h, args.steps, args.cfg, args.sampler, args.seed)
            img.save(png)

        if args.overwrite or not mp4.exists():
            if args.t2v == "svd":
                if Path(args.svd_python).exists():
                    try:
                        call_svd_self_in_venv(
                            args.svd_python, this_file, str(png), str(mp4),
                            args.fps, d, args.w, args.h, args.encoder,
                            args.svd_model, args.motion_bucket, args.noise_aug
                        )
                    except Exception as e:
                        print(f"⚠️ SVD 실패: {e}\n→ Ken Burns로 폴백합니다.")
                        make_kenburns(str(png), str(mp4), args.fps, d, args.w, args.h, args.encoder)
                else:
                    print("⚠️ SVD venv 미발견 → Ken Burns로 폴백")
                    make_kenburns(str(png), str(mp4), args.fps, d, args.w, args.h, args.encoder)
            else:
                make_kenburns(str(png), str(mp4), args.fps, d, args.w, args.h, args.encoder)

        pngs.append(str(png)); mp4s.append(str(mp4))

    # 합치기
    concat = outdir/"concat.txt"
    with open(concat, "w", encoding="utf-8") as f:
        for m in mp4s: f.write(f"file '{Path(m).resolve()}'\n")

    all_mp4 = outdir/"all_video.mp4"
    try:
        run_cmd(f'ffmpeg -y -loglevel error -f concat -safe 0 -i "{concat}" -c copy "{all_mp4}"')
    except:
        run_cmd(f'ffmpeg -y -loglevel error -f concat -safe 0 -i "{concat}" -vf format=yuv420p {enc_args(args.encoder)} "{all_mp4}"')

    print(f"\n✅ Done!  Shots: {len(shots)}  →  {all_mp4}")

if __name__ == "__main__":
    main()
