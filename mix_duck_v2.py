import argparse
from pathlib import Path
import torch, torchaudio

def db_to_lin(db): return 10.0**(db/20.0)

def to_float(x):
    return x.float()/32768.0 if x.dtype==torch.int16 else x.float()

def ensure_stereo(vox, bgm_channels):
    # 보이스가 모노이고 BGM이 스테레오면 중앙에 복제
    if vox.size(0)==1 and bgm_channels==2:
        vox = vox.repeat(2,1)
    return vox

def moving_avg_same(x_1d: torch.Tensor, win: int):
    """
    |x|에 대한 이동평균 (길이 동일 보장)
    - win은 홀수로 강제
    - 길이 차이는 crop/pad로 정확히 맞춤
    """
    x = x_1d.abs()
    L = x.numel()
    win = max(3, int(win) | 1)  # 홀수 보장
    pad = (win - 1) // 2
    w = torch.ones(1,1,win, device=x.device) / win
    y = torch.nn.functional.conv1d(x.view(1,1,-1), w, padding=pad).view(-1)
    if y.numel() > L:
        y = y[:L]
    elif y.numel() < L:
        y = torch.nn.functional.pad(y, (0, L - y.numel()), value=y[-1].item())
    return y.clamp_min(1e-6)

def sidechain_gain(env_lin_1d: torch.Tensor, thr_db=-32.0, ratio=6.0):
    env_db = 20*torch.log10(env_lin_1d.clamp_min(1e-6))
    over = (env_db - thr_db).clamp_min(0.0)
    red_db = over * (1.0 - 1.0/ratio)
    return db_to_lin(-red_db)

def resample_if_needed(x, sr, target_sr):
    return (torchaudio.functional.resample(x, sr, target_sr), target_sr) if sr!=target_sr else (x, sr)

def main(args):
    device = "cpu"
    # 로드
    bgm, sr_bgm = torchaudio.load(args.bgm)
    vox, sr_vox = torchaudio.load(args.voice)

    bgm = to_float(bgm)
    vox = to_float(vox)

    # 48k로 통일
    target_sr = 48000
    bgm, _ = resample_if_needed(bgm, sr_bgm, target_sr)
    vox, _ = resample_if_needed(vox, sr_vox, target_sr)

    # 길이 맞추기(짧은 쪽 기준)
    L = min(bgm.size(-1), vox.size(-1))
    bgm = bgm[..., :L]
    vox = vox[..., :L]

    # BGM 전처리: HPF/LPF + 3kHz -4dB + 볼륨
    bgm = torchaudio.functional.highpass_biquad(bgm, target_sr, cutoff_freq=70.0)
    bgm = torchaudio.functional.lowpass_biquad(bgm, target_sr, cutoff_freq=12000.0)
    bgm = torchaudio.functional.equalizer_biquad(bgm, target_sr, center_freq=3000.0, gain=-4.0, Q=1.1)
    bgm = bgm * 0.15

    # 보이스 에너지 → 사이드체인 게인
    # (모노로 평균 후 envelope, 윈도우는 각각 홀수로 잡음)
    vox_mono = vox.mean(dim=0)
    env = moving_avg_same(vox_mono, win=int(target_sr*0.050))   # 50ms
    gain = sidechain_gain(env, thr_db=-32.0, ratio=6.0)
    gain = moving_avg_same(gain, win=int(target_sr*0.200))      # release 200ms 스무딩
    gain = gain.clamp(0.05, 1.0)                                # 과도한 duck 방지

    # 채널로 브로드캐스트
    gain_st = gain.view(1, -1).repeat(bgm.size(0), 1)

    # 혹시라도 길이 오차 있으면 마지막으로 강제 정렬
    L2 = min(bgm.size(-1), vox.size(-1), gain_st.size(-1))
    bgm = bgm[..., :L2]
    vox = vox[..., :L2]
    gain_st = gain_st[..., :L2]

    # 덕킹
    ducked = bgm * gain_st

    # 합치기 & 스테레오 정리
    vox = ensure_stereo(vox, bgm_channels=bgm.size(0))
    mix = (vox + ducked).clamp(-1, 1)

    # 피크 -1dBFS 마진
    peak = float(mix.abs().max())
    if peak > 0:
        mix = mix / peak * db_to_lin(-1.0)

    # 저장(WAV, int16)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(out), (mix*32767).short().cpu(), sample_rate=target_sr)
    print(f"[OK] wrote {out}  (len={L2} samples @ {target_sr} Hz)")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bgm", required=True)
    ap.add_argument("--voice", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    main(args)
