
# YT Auto Pipeline (topic → moving visuals + TTS → mp4)

This repo turns a **topic** into a **YouTube‑ready video** with **moving images** (pan/zoom or AnimateDiff) and **TTS + SRT**, then emits **metadata files** (title/description/hashtags) like your Upload Script Kit.

> ✅ Works *out of the box* with a lightweight fallback (no external models).  
> 🔌 Optional: **ComfyUI (AnimateDiff)** for animated shots.  
> 🔊 Optional TTS engines: **edge‑tts**, **melo‑tts** (CLI wrapper), or **pyttsx3** (offline).

---

## Quickstart

1) **Requirements**
- Python 3.10+
- `ffmpeg` in PATH (`ffmpeg -version`)
- (Optional) `edge-tts` (`pip install edge-tts`) – easy, good quality
- (Optional) ComfyUI running (e.g. on WSL2) with AnimateDiff workflow exported as JSON
- (Optional) melo‑tts CLI installed and on PATH

2) **Install deps**
```bash
cd yt_auto_pipeline
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

3) **Run (fallback, no models)**
```bash
python src/main.py \
  --topic "블루아카 캐릭터 추천 TOP5" \
  --lang ko \
  --out out/demo1 \
  --tts_engine edge \
  --fps 30 --size 1080x1920 \
  --mock
```
This generates:
- `out/demo1/final.mp4` (vertical)
- `out/demo1/final.srt`
- `out/demo1/meta/ko.title.txt`, `ko.desc.txt`, `ko.hashtags.txt`

4) **Run with ComfyUI (AnimateDiff)**
- Export an AnimateDiff workflow JSON from ComfyUI.
- Identify the **positive text** input node id and (optional) **neg prompt** node id.
```bash
python src/main.py \
  --topic "밤하늘의 신비로운 마녀 이야기" \
  --lang ko \
  --out out/demo_anim \
  --tts_engine edge \
  --animate \
  --comfyui_url http://127.0.0.1:8188 \
  --workflow workflows/animate_diff_placeholder.json \
  --prompt_node 23 \
  --neg_prompt_node 27
```
If ComfyUI is not reachable or the workflow fails, the pipeline automatically falls back to **Ken Burns** motion on generated stills.

5) **Use your own script**
If you already have a script, skip the LLM step:
```bash
python src/main.py --script path/to/script.txt --out out/manual --lang ko --tts_engine edge --mock
```

---

## Notes

- **LLM**: By default, we synthesize a decent script from your `--topic` using a simple template (no network).
  - To use an OpenAI‑compatible server (e.g. your local Qwen/vLLM), set env vars and pass `--llm openai`:
    - `export LLM_API_BASE=http://127.0.0.1:8000/v1`
    - `export LLM_API_KEY=sk-local-123`
    - `export LLM_MODEL=qwen2.5-14b-instruct`
  - Then:
    ```bash
    python src/main.py --topic "..." --llm openai --out out/llm
    ```

- **TTS**:
  - `--tts_engine edge` (recommended; needs internet)
  - `--tts_engine melo` (expects `melo_tts` CLI on PATH)
  - `--tts_engine pyttsx3` (offline basic; Linux may require `espeak`)
  - voice options: `--voice zh-CN-XiaoxiaoNeural`, `--voice ko-KR-SunHiNeural`, etc. (Edge voices)

- **ComfyUI**: Provide a JSON workflow. We set the text prompt nodes per‑shot, queue it, poll for completion, and collect images (or short mp4s) per shot.

- **Output layout** mirrors your Upload Script Kit style:
  - `out/<name>/meta/ko.title.txt`, `ko.desc.txt`, `ko.hashtags.txt`, `ko.pinned.txt`

- **Aspect ratios**: Use `--size 1920x1080` for 16:9, `--size 1080x1920` for Shorts.

---

## Troubleshooting

- **ffmpeg not found**: install it and ensure `ffmpeg` in PATH.
- **edge-tts errors**: check internet; try a different voice, or switch `--tts_engine pyttsx3`.
- **ComfyUI**: confirm `curl http://127.0.0.1:8188` works. Ensure your workflow JSON has the prompt node ids you pass.
- **Audio/Video desync**: We compute segment durations from actual audio lengths via ffprobe; if you edit audio externally, re-run `--stitch_only`.

---

## License

MIT (for these scripts). You are responsible for assets/models you use.
