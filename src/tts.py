import os, subprocess, tempfile, asyncio
from typing import List
from .utils.ffmpeg import probe_duration

def tts_edge(texts: List[str], out_dir: str, voice="ko-KR-SunHiNeural", rate="+0%", volume="+0%"):
    import edge_tts  # pip install edge-tts
    os.makedirs(out_dir, exist_ok=True)
    loop = asyncio.get_event_loop()
    async def synth_one(i, t):
        out = os.path.join(out_dir, f"seg_{i:03d}.mp3")
        communicate = edge_tts.Communicate(t, voice=voice, rate=rate, volume=volume)
        await communicate.save(out)
        return out
    async def run_all():
        return await asyncio.gather(*[synth_one(i, t) for i, t in enumerate(texts)])
    return loop.run_until_complete(run_all())

def tts_melo(texts: List[str], out_dir: str, voice="KOR_FEMALE"):
    """
    Expects `melo_tts` CLI to be available on PATH.
    We avoid shell quoting by passing args as a list.
    """
    os.makedirs(out_dir, exist_ok=True)
    outs = []
    for i, t in enumerate(texts):
        out = os.path.join(out_dir, f"seg_{i:03d}.wav")
        cmd = ["melo_tts", "--text", t, "--voice", voice, "--output", out]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[:1000])
        outs.append(out)
    return outs

def tts_pyttsx3(texts: List[str], out_dir: str, voice=None, rate=180):
    import pyttsx3
    os.makedirs(out_dir, exist_ok=True)
    engine = pyttsx3.init()
    engine.setProperty('rate', rate)
    outs = []
    for i, t in enumerate(texts):
        out = os.path.join(out_dir, f"seg_{i:03d}.wav")
        engine.save_to_file(t, out)
        engine.runAndWait()
        outs.append(out)
    return outs

def get_audio_durations(paths: List[str]):
    return [probe_duration(p) for p in paths]
