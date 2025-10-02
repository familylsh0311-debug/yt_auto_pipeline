import os, sys, subprocess, datetime, random, json
from pathlib import Path
import torch, torchaudio
from einops import rearrange
from huggingface_hub import HfFolder, hf_hub_download
from stable_audio_tools import get_pretrained_model
from stable_audio_tools.inference.generation import generate_diffusion_cond

# ===== 설정 =====
SECONDS = 30                   # 정확히 30초 보장
TARGET_SR = 48000              # 비디오 파이프라인 호환↑
STEPS = 100
CFG_SCALE = 7
SAMPLER = "dpmpp-3m-sde"
FADE_IN = 0.5                  # 초
FADE_OUT = 1.0                 # 초
FFMPEG = "ffmpeg"

# "no vocals / no lead / understated" 강화 프롬프트
PRESETS = {
  "lofi_chillhop_mellow":
    "instrumental only, no vocals, no lead melody, understated, lofi chillhop, 90 BPM, warm Rhodes, soft dusty drums, simple repeating motif, cozy, clean mix, background",
  "ambient_cinematic_light":
    "instrumental only, no vocals, no lead melody, understated, cinematic ambient underscore, slow evolving pads and piano, minimal percussion, wide reverb, gentle, background",
  "synthwave_bg_no_lead":
    "instrumental only, no vocals, no lead melody, understated, synthwave background, 100 BPM, analog pads, light arpeggio, soft sidechain, clean mix, background",
  "minimal_house_soft":
    "instrumental only, no vocals, no lead melody, understated, minimal deep house, 120 BPM, soft kick and hat, warm bass, simple chord stab, low complexity, background",
  "acoustic_folk_warm":
    "instrumental only, no vocals, no lead melody, understated, warm acoustic folk underscore, soft nylon guitar, light shaker, mellow, simple motif, background",
}
N_VARIANTS_PER_PRESET = 2      # 각 프리셋 당 시드 2개 만들어서 픽

VOICE_PATH = Path("voice.wav") # 있으면 자동 믹스
OUT_ROOT = Path("assets") / "bgm_30s" / datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

# ===== 유틸 =====
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

def to_int16(audio: torch.Tensor):
    audio = audio.float()
    peak = audio.abs().max()
    if peak > 0:
        audio = audio / peak
    return (audio.clamp(-1, 1) * 32767).to(torch.int16).cpu()

def save_wav(path: Path, audio: torch.Tensor, sr: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(path), audio, sr)

def band_energy_metrics(audio: torch.Tensor, sr: int):
    """
    간단 스펙트럼 분석으로 대역별 에너지 비율과 mid_mask_index 산출.
    audio: (C, N) [-1,1]
    """
    mono = audio.mean(dim=0)
    N = 1
    L = mono.numel()
    while N < L: N <<= 1
    win = torch.hann_window(L, device=mono.device)
    z = torch.zeros(N, device=mono.device)
    z[:L] = mono * win
    spec = torch.fft.rfft(z)
    mag = spec.abs()
    freqs = torch.fft.rfftfreq(N, 1.0/sr)
    total = mag.sum() + 1e-12
    def band(lo, hi):
        idx = (freqs >= lo) & (freqs < hi)
        return float(mag[idx].sum() / total)
    bands = {
        "low_20_200": band(20, 200),
        "lowmid_200_2000": band(200, 2000),
        "mid_2000_5000": band(2000, 5000),
        "high_5k_12k": band(5000, 12000),
        "air_12k_20k": band(12000, min(20000, sr/2)),
    }
    centroid = float((freqs * mag).sum() / total)
    # 말과 충돌 가능성 척도(낮을수록 좋음)
    mid_mask_index = bands["mid_2000_5000"] + 0.5 * bands["high_5k_12k"]
    return bands, centroid, float(mid_mask_index)

def process_audio(post_audio: torch.Tensor, src_sr: int):
    """
    1) 정확히 30초로 트림
    2) 페이드 인/아웃
    3) 48kHz로 리샘플
    """
    total_needed = int(SECONDS * src_sr)
    if post_audio.shape[-1] < total_needed:
        # 짧으면 0-pad
        pad = total_needed - post_audio.shape[-1]
        post_audio = torch.nn.functional.pad(post_audio, (0, pad))
    # 슬라이스 30s
    post_audio = post_audio[:, :total_needed]
    # 페이드
    post_audio = fade_in_out(post_audio, src_sr, FADE_IN, FADE_OUT)
    # 48kHz로 리샘플
    if src_sr != TARGET_SR:
        post_audio = torchaudio.functional.resample(post_audio, src_sr, TARGET_SR)
        sr = TARGET_SR
    else:
        sr = src_sr
    return post_audio, sr

def generate_variant(model, cfg, prompt, device, seed=None):
    if seed is not None:
        torch.manual_seed(seed)
        random.seed(seed)
    cond = [{"prompt": prompt, "seconds_start": 0, "seconds_total": SECONDS}]  # 모델이 고정 길이를 낼 수 있어도 후단에서 트림
    audio = generate_diffusion_cond(
        model, steps=STEPS, cfg_scale=CFG_SCALE, conditioning=cond,
        sample_size=cfg["sample_size"], sigma_min=0.3, sigma_max=500,
        sampler_type=SAMPLER, device=device
    )
    audio = rearrange(audio, "b d n -> d (b n)")   # (C, N)
    return audio, cfg["sample_rate"]

def mix_with_voice(bgm_path: Path):
    """
    보이스 -14LUFS, BGM HPF/LPF/EQ/볼륨, 보이스를 키로 BGM을 사이드체인 덕킹,
    amix + dynaudnorm. (ffmpeg 필요)
    """
    if not ensure_ffmpeg():
        print("[WARN] ffmpeg이 없어 자동 믹스를 건너뜁니다.")
        return None
    out_dir = Path("out/shorts_30s"); out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "all_audio.m4a"
    # 주의: sidechaincompress는 첫 입력을 압축하고, 두 번째 입력을 키로 씀.
    # => [bgm][vox] 순서가 맞다!
    filt = (
        "[0:a]highpass=f=70,lowpass=f=12000,"
        "equalizer=f=3000:t=q:w=1.1:g=-4,alimiter=limit=0.98,volume=0.14[bgm];"
        "[1:a]loudnorm=I=-14:TP=-1.5:LRA=9[vox];"
        "[bgm][vox]sidechaincompress=threshold=0.015:ratio=6:attack=5:release=200:makeup=3[ducked];"
        "[vox][ducked]amix=inputs=2:dropout_transition=2,dynaudnorm=f=75[mix]"
    )
    cmd = [
        FFMPEG, "-y",
        "-i", str(bgm_path),
        "-i", str(VOICE_PATH),
        "-filter_complex", filt,
        "-map", "[mix]", "-c:a", "aac", "-b:a", "256k",
        str(out_path)
    ]
    subprocess.run(cmd, check=True)
    return out_path

def main():
    # 0) Token & gated repo 체크
    if not HfFolder.get_token():
        print("ERROR: Hugging Face 토큰 없음. `hf auth login` 후 재시도.", file=sys.stderr)
        sys.exit(1)
    try:
        hf_hub_download("stabilityai/stable-audio-open-1.0", "model_config.json")
    except Exception:
        print("ERROR: 모델 접근 권한 필요. 브라우저에서 약관/Access 동의 후 재시도:\n"
              "https://huggingface.co/stabilityai/stable-audio-open-1.0", file=sys.stderr)
        sys.exit(1)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[INFO] device={device}")
    model, cfg = get_pretrained_model("stabilityai/stable-audio-open-1.0")
    model = model.to(device)

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    report = {"target_sr": TARGET_SR, "seconds": SECONDS, "tracks": []}

    base_seed = int(datetime.datetime.now().timestamp()) & 0xFFFFFFFF
    torch.manual_seed(base_seed); random.seed(base_seed)

    best_item = None  # (mid_mask_index, path, meta)

    for preset_name, prompt in PRESETS.items():
        for k in range(N_VARIANTS_PER_PRESET):
            seed = (base_seed + hash(preset_name) + k) & 0xFFFFFFFF
            print(f"[GEN] {preset_name} #{k+1} (seed={seed})")
            raw, sr = generate_variant(model, cfg, prompt, device, seed)
            post, sr2 = process_audio(raw, sr)

            # 리미터(피크 보호). torchaudio 기본엔 하드리미터 없으니 레벨 정규화 + alimiter는 믹스 단계에서.
            # 여기선 -0.1dBFS 근처로 맞춤
            peak = post.abs().max()
            if float(peak) > 0:
                post = post / peak * (10**(-0.1/20))

            # 저장 (48kHz int16)
            wav_path = OUT_ROOT / f"{preset_name}_s{seed}.wav"
            save_wav(wav_path, to_int16(post), sr2)

            # 분석
            bands, centroid, mid_mask_idx = band_energy_metrics(post, sr2)
            meta = {
                "preset": preset_name,
                "seed": seed,
                "path": str(wav_path),
                "sr": sr2,
                "bands": bands,
                "centroid_Hz": centroid,
                "mid_mask_index": mid_mask_idx
            }
            report["tracks"].append(meta)

            # 베스트(말 마스킹 최소) 갱신
            if (best_item is None) or (mid_mask_idx < best_item[0]):
                best_item = (mid_mask_idx, wav_path, meta)

            print(f"  -> saved: {wav_path} | mid_mask_index={mid_mask_idx:.4f}")

    # 베스트 복사
    if best_item:
        best_wav = OUT_ROOT / "bgm_best.wav"
        # 그냥 복사 대신, mp3도 함께 만들어줌
        subprocess.run([FFMPEG, "-y", "-i", str(best_item[1]), "-c:a", "copy", str(best_wav)], check=True)
        if ensure_ffmpeg():
            subprocess.run([FFMPEG, "-y", "-i", str(best_wav), "-c:a", "libmp3lame", "-q:a", "2",
                            str(best_wav.with_suffix(".mp3"))], check=True)
        report["best"] = best_item[2]
        print(f"[OK] 베스트 트랙: {best_wav} (mid_mask_index={best_item[0]:.4f})")

    # 보고서 저장
    with open(OUT_ROOT / "report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 보이스 자동 믹스
    if VOICE_PATH.exists() and best_item:
        try:
            mixed = mix_with_voice(best_item[1])
            if mixed: print(f"[OK] 내레이션 믹스 생성: {mixed}")
        except subprocess.CalledProcessError as e:
            print(f"[WARN] 믹스 실패: {e}")
    else:
        print("[INFO] voice.wav 없음 또는 베스트 미선정 → 믹스 스킵.")

    print(f"[DONE] 출력 폴더: {OUT_ROOT}")

if __name__ == "__main__":
    main()
