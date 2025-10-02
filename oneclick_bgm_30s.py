import os, sys, subprocess, datetime, random
from pathlib import Path
import torch, torchaudio
from einops import rearrange
from huggingface_hub import HfFolder, hf_hub_download
from stable_audio_tools import get_pretrained_model
from stable_audio_tools.inference.generation import generate_diffusion_cond

# ====== 설정 ======
SECONDS = 30
STEPS = 100
CFG_SCALE = 7
SAMPLER = "dpmpp-3m-sde"
FADE_IN = 0.5   # 초
FADE_OUT = 1.0  # 초
PRESETS = {
    "lofi_chillhop_mellow":
        "instrumental only, no vocals, lofi chillhop, 90 BPM, warm Rhodes, soft dusty drums, simple repeating motif, cozy, clean mix, background",
    "ambient_cinematic_light":
        "instrumental only, no vocals, cinematic ambient underscore, slow evolving pads and piano, minimal percussion, wide reverb, gentle, background",
    "synthwave_bg_no_lead":
        "instrumental only, no vocals, synthwave background, 100 BPM, analog pads, light arpeggio, soft sidechain, no prominent lead, clean mix",
    "minimal_house_soft":
        "instrumental only, no vocals, minimal deep house, 120 BPM, soft kick and hat, warm bass, simple chord stab, low complexity, background",
    "acoustic_folk_warm":
        "instrumental only, no vocals, warm acoustic folk underscore, soft nylon guitar, light shaker, mellow, simple motif, background",
}
PREFERRED_FOR_MIX = "lofi_chillhop_mellow"  # voice.wav 있으면 이 트랙과 자동 믹스
OUT_ROOT = Path("assets") / "bgm_30s" / datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
VOICE_PATH = Path("voice.wav")  # 있으면 자동 믹스
FFMPEG = "ffmpeg"

# ====== 유틸 ======
def ensure_ffmpeg():
    from shutil import which
    return which(FFMPEG) is not None

def fade_in_out(audio: torch.Tensor, sr: int, t_in=0.5, t_out=1.0):
    # audio: (C, N)
    n = audio.shape[-1]
    env = torch.ones(n, device=audio.device, dtype=audio.dtype)
    fi = int(sr * max(0.0, t_in))
    fo = int(sr * max(0.0, t_out))
    if fi > 0:
        env[:fi] = torch.linspace(0, 1, fi, device=audio.device, dtype=audio.dtype)
    if fo > 0:
        env[-fo:] = torch.linspace(1, 0, fo, device=audio.device, dtype=audio.dtype)
    return audio * env.unsqueeze(0)

def save_wav_int16(path: Path, audio: torch.Tensor, sr: int):
    # [-1,1] -> int16
    audio = audio.float()
    peak = audio.abs().max()
    if peak > 0:
        audio = audio / peak
    audio = (audio.clamp(-1, 1) * 32767).to(torch.int16).cpu()
    path.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(path), audio, sr)

def mix_with_voice(bgm_wav: Path):
    if not ensure_ffmpeg():
        print("[WARN] ffmpeg이 없어 자동 믹스를 건너뜁니다.")
        return None
    out_dir = Path("out/shorts_30s"); out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "all_audio.m4a"
    cmd = [
        FFMPEG, "-y",
        "-i", str(VOICE_PATH),
        "-i", str(bgm_wav),
        "-filter_complex",
        "[0:a]loudnorm=I=-14:TP=-1.5:LRA=9[vox];"
        "[1:a]volume=0.16[bgm];"
        "[vox][bgm]amix=inputs=2:dropout_transition=2,dynaudnorm=f=75",
        "-c:a", "aac", "-b:a", "256k",
        str(out_path)
    ]
    subprocess.run(cmd, check=True)
    return out_path

# ====== 시작 ======
def main():
    # HF 토큰/접근 체크
    if not HfFolder.get_token():
        print("ERROR: Hugging Face 토큰이 없습니다. `hf auth login` 후 다시 실행하세요.", file=sys.stderr)
        sys.exit(1)
    try:
        hf_hub_download("stabilityai/stable-audio-open-1.0", "model_config.json")
    except Exception as e:
        print("ERROR: 모델 접근 권한이 없습니다. 브라우저에서 약관 동의/Access 요청 후 재시도.\n"
              "URL: https://huggingface.co/stabilityai/stable-audio-open-1.0", file=sys.stderr)
        raise

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[INFO] device={device}")
    model, cfg = get_pretrained_model("stabilityai/stable-audio-open-1.0")
    model = model.to(device)

    generated = []
    # 시드 고정(재현성). 각 프리셋마다 다른 시드
    base_seed = int(datetime.datetime.now().timestamp()) & 0xFFFFFFFF
    torch.manual_seed(base_seed)
    random.seed(base_seed)

    for i, (slug, prompt) in enumerate(PRESETS.items(), 1):
        print(f"[GEN {i}/{len(PRESETS)}] {slug}")
        cond = [{
            "prompt": prompt,
            "seconds_start": 0,
            "seconds_total": SECONDS
        }]

        # 생성
        audio = generate_diffusion_cond(
            model, steps=STEPS, cfg_scale=CFG_SCALE, conditioning=cond,
            sample_size=cfg["sample_size"], sigma_min=0.3, sigma_max=500,
            sampler_type=SAMPLER, device=device
        )
        # (B, C, N) -> (C, N), 페이드
        audio = rearrange(audio, "b d n -> d (b n)")
        audio = fade_in_out(audio, cfg["sample_rate"], FADE_IN, FADE_OUT)

        # 저장
        wav_path = OUT_ROOT / f"{slug}.wav"
        save_wav_int16(wav_path, audio, cfg["sample_rate"])
        print(f"  -> {wav_path}")
        generated.append(wav_path)

        # mp3도 저장(있다면 ffmpeg)
        if ensure_ffmpeg():
            mp3_path = wav_path.with_suffix(".mp3")
            subprocess.run([FFMPEG, "-y", "-i", str(wav_path), "-c:a", "libmp3lame", "-q:a", "2", str(mp3_path)], check=True)
            print(f"  -> {mp3_path}")

    print("\n[OK] 생성 완료.")
    print(f"출력 폴더: {OUT_ROOT}")

    # 자동 믹스(voice.wav 있을 때)
    if VOICE_PATH.exists():
        key = PREFERRED_FOR_MIX if any(p.stem == PREFERRED_FOR_MIX for p in generated) else generated[0].stem
        bgm_target = OUT_ROOT / f"{key}.wav"
        try:
            mixed = mix_with_voice(bgm_target)
            if mixed:
                print(f"[OK] 내레이션 믹스 생성: {mixed}")
        except subprocess.CalledProcessError as e:
            print(f"[WARN] 믹스 실패: {e}")
    else:
        print("[INFO] voice.wav 파일이 없어 자동 믹스를 건너뜁니다.")

if __name__ == "__main__":
    main()
