import argparse
from pathlib import Path
import torch, torchaudio

def db_to_lin(db): return 10.0**(db/20.0)

def to_float(x): return x.float()/32768.0 if x.dtype==torch.int16 else x.float()

def resample_if_needed(x, sr, target_sr):
    return (torchaudio.functional.resample(x, sr, target_sr), target_sr) if sr!=target_sr else (x, sr)

def moving_avg_same(x_1d: torch.Tensor, win: int):
    L = x_1d.numel()
    win = max(3, int(win) | 1)  # 홀수 보장
    pad = (win - 1) // 2
    w = torch.ones(1,1,win, device=x_1d.device) / win
    y = torch.nn.functional.conv1d(x_1d.abs().view(1,1,-1), w, padding=pad).view(-1)
    if y.numel() > L: y = y[:L]
    elif y.numel() < L: y = torch.nn.functional.pad(y, (0, L - y.numel()), value=y[-1].item())
    return y.clamp_min(1e-6)

def sidechain_gain(env_lin_1d: torch.Tensor, thr_db=-32.0, ratio=6.0):
    env_db = 20*torch.log10(env_lin_1d.clamp_min(1e-6))
    over = (env_db - thr_db).clamp_min(0.0)
    red_db = over * (1.0 - 1.0/ratio)
    return db_to_lin(-red_db)

def apply_fade(x, sr, fin_s=0.15, fout_s=0.25):
    L = x.size(-1)
    fin = int(sr*fin_s); fout = int(sr*fout_s)
    ramp_in  = torch.linspace(0,1,steps=max(1,fin),  device=x.device)
    ramp_out = torch.linspace(1,0,steps=max(1,fout), device=x.device)
    y = x.clone()
    if fin>0:  y[..., :fin]  *= ramp_in
    if fout>0: y[..., -fout:] *= ramp_out
    return y

def ensure_stereo(vox, bgm_channels):
    return vox.repeat(2,1) if vox.size(0)==1 and bgm_channels==2 else vox

def tpdf_dither(x, lsb=1.0/32768.0):
    # 16-bit용 TPDF 디더(±1 LSB 삼각분포)
    n = (torch.rand_like(x) - 0.5 + torch.rand_like(x) - 0.5) * lsb
    return (x + n).clamp(-1, 1)

def main(args):
    # 로드
    bgm, sr_bgm = torchaudio.load(args.bgm)
    vox, sr_vox = torchaudio.load(args.voice)
    bgm, vox = to_float(bgm), to_float(vox)

    # 48k 통일
    target_sr = 48000
    bgm, _ = resample_if_needed(bgm, sr_bgm, target_sr)
    vox, _ = resample_if_needed(vox, sr_vox, target_sr)

    # 길이 맞추기(짧은 쪽)
    L = min(bgm.size(-1), vox.size(-1))
    bgm, vox = bgm[..., :L], vox[..., :L]

    # --- 보이스 전처리 ---
    # HPF 80 Hz + 라이트 디에서(7.5kHz -3 dB 노치)
    vox = torchaudio.functional.highpass_biquad(vox, target_sr, cutoff_freq=80.0)
    vox = torchaudio.functional.equalizer_biquad(vox, target_sr, center_freq=7500.0, gain=-3.0, Q=2.0)

    # --- BGM 전처리 ---
    bgm = torchaudio.functional.highpass_biquad(bgm, target_sr, cutoff_freq=70.0)
    bgm = torchaudio.functional.lowpass_biquad(bgm, target_sr, cutoff_freq=12000.0)
    bgm = torchaudio.functional.equalizer_biquad(bgm, target_sr, center_freq=3000.0, gain=-4.0, Q=1.1)
    bgm = apply_fade(bgm, target_sr, fin_s=0.15, fout_s=0.25)
    bgm = bgm * args.bgm_gain

    # --- 사이드체인 ---
    vox_mono = vox.mean(dim=0)
    env = moving_avg_same(vox_mono, win=int(target_sr*args.attack_ms/1000.0))
    gain = sidechain_gain(env, thr_db=args.thr_db, ratio=args.ratio)
    gain = moving_avg_same(gain, win=int(target_sr*args.release_ms/1000.0))
    gain = gain.clamp(0.05, 1.0)
    gain_st = gain.view(1,-1).repeat(bgm.size(0),1)

    # 정렬 안전장치
    L2 = min(bgm.size(-1), vox.size(-1), gain_st.size(-1))
    bgm, vox, gain_st = bgm[..., :L2], vox[..., :L2], gain_st[..., :L2]

    # 덕킹 + 합
    ducked = bgm * gain_st
    vox = ensure_stereo(vox, bgm_channels=bgm.size(0))
    mix = (vox + ducked).clamp(-1, 1)

    # 피크 -1 dBFS
    peak = float(mix.abs().max())
    if peak > 0: mix = mix/peak * db_to_lin(-1.0)

    # 디더 후 16-bit 저장
    mix16 = (tpdf_dither(mix) * 32767).short().cpu()
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(out), mix16, sample_rate=target_sr)
    print(f"[OK] wrote {out}  (len={L2} @ {target_sr} Hz)")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bgm",   required=True)
    ap.add_argument("--voice", required=True)
    ap.add_argument("--out",   required=True)
    ap.add_argument("--bgm_gain", type=float, default=0.15)
    ap.add_argument("--thr_db",   type=float, default=-32.0)  # 더 강하게: -35
    ap.add_argument("--ratio",    type=float, default=6.0)    # 더 강하게: 8
    ap.add_argument("--attack_ms",type=float, default=50.0)
    ap.add_argument("--release_ms",type=float, default=180.0)
    args = ap.parse_args()
    main(args)
