import os, argparse, yaml, textwrap, shutil, json, math
from typing import List, Dict, Any
from .script_shots import synthesize_script_from_topic, parse_script, load_template
from .visuals import build_shot_video
from .tts import tts_edge, tts_melo, tts_pyttsx3, get_audio_durations
from .assemble import write_srt, concat_videos, mix_audio, mux_av, overlay_music, write_metadata

def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)

def generate_script(args, cfg):
    # If user provided script file, use it as-is
    if args.script and os.path.exists(args.script):
        with open(args.script, "r", encoding="utf-8") as f:
            return f.read()

    # Else synthesize from topic (template or OpenAI-compatible)
    provider = (args.llm or cfg.get("llm", {}).get("provider") or "template").lower()
    if provider == "openai" and os.environ.get("LLM_API_BASE") and os.environ.get("LLM_API_KEY"):
        import requests
        base = os.environ["LLM_API_BASE"].rstrip("/")
        key  = os.environ["LLM_API_KEY"]
        model= os.environ.get("LLM_MODEL","gpt-3.5-turbo")
        prompt = load_template(os.path.join(args.root, "prompts", f"script_{args.lang}.j2"), topic=args.topic)
        body = {
            "model": model,
            "messages": [
                {"role":"system","content":"You are an excellent Korean YouTube scriptwriter."},
                {"role":"user","content":prompt}
            ],
            "temperature": 0.7,
        }
        r = requests.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=body, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    # Fallback template synth
    return synthesize_script_from_topic(args.topic, args.lang, os.path.join(args.root,"prompts", f"script_{args.lang}.j2"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", type=str, default=None, help="Topic to write about")
    ap.add_argument("--script", type=str, help="Use existing script file (txt/md/srt/json)")
    ap.add_argument("--script_mode", type=str, default="auto", choices=["auto","txt","md","markdown","srt","json"])
    ap.add_argument("--lang", type=str, default="ko")
    ap.add_argument("--out", type=str, required=True)
    ap.add_argument("--fps", type=int, default=None)
    ap.add_argument("--size", type=str, default=None, help="e.g., 1080x1920")
    ap.add_argument("--tts_engine", type=str, default=None, choices=["edge","melo","pyttsx3"])
    ap.add_argument("--voice", type=str, default=None)
    ap.add_argument("--rate", type=str, default="+0%")
    ap.add_argument("--volume", type=str, default="+0%")
    ap.add_argument("--mock", action="store_true", help="Use simple visuals (Ken Burns) even if ComfyUI is configured")
    ap.add_argument("--animate", action="store_true", help="Try ComfyUI / AnimateDiff if available")
    ap.add_argument("--comfyui_url", type=str, default=None)
    ap.add_argument("--workflow", type=str, default=None)
    ap.add_argument("--prompt_node", type=int, default=None)
    ap.add_argument("--neg_prompt_node", type=int, default=None)
    ap.add_argument("--music", type=str, default=None)
    ap.add_argument("--llm", type=str, default=None, choices=["template","openai"])
    ap.add_argument("--stitch_only", action="store_true", help="Skip generation; just stitch existing segments in out dir")
    ap.add_argument("--target_secs", type=float, default=70.0)
    ap.add_argument("--min_shots", type=int, default=6)
    ap.add_argument("--max_shots", type=int, default=10)
    args = ap.parse_args()

    args.root = os.path.dirname(os.path.abspath(__file__ + "/.."))

    # Load config & defaults
    cfg_path = os.path.join(args.root, "config.yaml")
    cfg = yaml.safe_load(open(cfg_path, "r", encoding="utf-8"))
    ensure_dir(args.out)

    if args.fps is None: args.fps = cfg["render"]["fps"]
    if args.size is None: args.size = cfg["render"]["size"]
    if args.tts_engine is None: args.tts_engine = cfg["tts"]["engine"]
    if args.voice is None: args.voice = cfg["tts"]["voice"]
    if args.music is None: args.music = cfg["render"].get("music")

    comfy_cfg = None
    if args.animate and not args.mock:
        comfy_cfg = {
            "url": args.comfyui_url or cfg["comfyui"]["url"],
            "workflow_path": args.workflow or cfg["comfyui"]["workflow_path"],
            "prompt_node": args.prompt_node or cfg["comfyui"]["prompt_node"],
            "neg_prompt_node": args.neg_prompt_node if args.neg_prompt_node is not None else cfg["comfyui"].get("neg_prompt_node")
        }

    # 1) Script
    script_txt_path = os.path.join(args.out, "script.txt")
    if not args.stitch_only:
        if not args.topic and not args.script:
            raise SystemExit("--topic or --script is required (unless --stitch_only).")
        script = generate_script(args, cfg)
        open(script_txt_path, "w", encoding="utf-8").write(script)
    else:
        script = open(script_txt_path, "r", encoding="utf-8").read()

    # 2) Shots
    shots = parse_script(script, mode=args.script_mode, target_secs=args.target_secs,
                         min_shots=args.min_shots, max_shots=args.max_shots)
    shots_path = os.path.join(args.out, "shots.json")
    open(shots_path, "w", encoding="utf-8").write(json.dumps(shots, ensure_ascii=False, indent=2))

    # 3) TTS per shot
    audio_dir = os.path.join(args.out, "audio"); ensure_dir(audio_dir)
    texts = [s["text"] for s in shots]
    if not args.stitch_only:
        if args.tts_engine == "edge":
            audio_paths = tts_edge(texts, audio_dir, voice=args.voice, rate=args.rate, volume=args.volume)
        elif args.tts_engine == "melo":
            audio_paths = tts_melo(texts, audio_dir)
        else:
            audio_paths = tts_pyttsx3(texts, audio_dir)
    else:
        audio_paths = sorted([os.path.join(audio_dir, f) for f in os.listdir(audio_dir) if f.lower().endswith((".mp3",".wav",".m4a"))])

    durs = get_audio_durations(audio_paths)
    for idx, s in enumerate(shots):
        ad = max(0.5, durs[idx] if idx < len(durs) else 0.0)
        s["dur"] = float(s.get("secs") or ad or 3.0)
    open(shots_path, "w", encoding="utf-8").write(json.dumps(shots, ensure_ascii=False, indent=2))

    # 4) Visual per shot
    video_dir = os.path.join(args.out, "video"); ensure_dir(video_dir)
    video_paths = []
    if not args.stitch_only:
        for i, s in enumerate(shots):
            tmp_dir = os.path.join(video_dir, f"seg_{i:03d}"); ensure_dir(tmp_dir)
            vp = build_shot_video(
                text=s["text"],
                prompt=s.get("prompt") or f"cinematic, high detail, key idea: {s['text']}",
                size=args.size,
                secs=s["dur"],
                tmp_dir=tmp_dir,
                use_comfy=bool(comfy_cfg) and (not args.mock),
                comfy_cfg=comfy_cfg
            )
            video_paths.append(vp)
    else:
        for i in range(len(shots)):
            p = os.path.join(video_dir, f"seg_{i:03d}", "shot.mp4")
            if os.path.exists(p): video_paths.append(p)

    # 5) Concatenate A/V
    allv = os.path.join(args.out, "all_video.mp4")
    concat_videos(video_paths, allv)
    alla = os.path.join(args.out, "all_audio.m4a")
    mix_audio(audio_paths, alla)

    # 6) Optional BGM ducking
    final_audio = alla
    if args.music and os.path.exists(args.music):
        bgmixed = os.path.join(args.out, "audio_bgm.m4a")
        overlay_music(alla, args.music, bgmixed, music_db=-18)
        final_audio = bgmixed

    # 7) Optional loudness normalization (-14 LUFS). Skip silently if helper not present.
    try:
        from .assemble import normalize_audio
        norm_audio = os.path.join(args.out, "final_norm.m4a")
        normalize_audio(final_audio, norm_audio)
        final_audio = norm_audio
    except Exception:
        pass

    # 8) Mux
    final_mp4 = os.path.join(args.out, "final.mp4")
    mux_av(allv, final_audio, final_mp4)

    # 9) Subtitles
    srt_path = os.path.join(args.out, "final.srt")
    srt_segments = [{"text": s["text"], "dur": s["dur"]} for s in shots]
    write_srt(srt_segments, srt_path)

    # 10) Metadata
    title = (shots[0]["text"][:40] + " | 1분 요약") if shots else "Auto Video"
    desc = script
    hashtags = ["Shorts","스크립트기반","자동"] + ([w for w in (args.topic or "").split()[:2]] if args.topic else [])
    write_metadata(args.out, args.lang, title, desc, hashtags)

    print("\nDone.")
    print("Video:", final_mp4)
    print("SRT  :", srt_path)
    print("Meta :", os.path.join(args.out, "meta"))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
