import argparse
from pathlib import Path
import torch, torchaudio

def db_to_lin(db): return 10.0**(db/20.0)
def to_float(x):   return x.float()/32768.0 if x.dtype==torch.int16 else x.float()

def resample_if_needed(x, sr, target_sr):
    return (torchaudio.functional.resample(x, sr, target_sr), target_sr) if sr!=target_sr else (x, sr)

def moving_avg_same(x_1d: torch.Tensor, win: int):
    L = x_1d.numel()
    win = max(3, int(win) | 1)              # 홀수 보장
    pad = (win - 1) // 2
    w = torch.ones(1,1,win, device=x_1d.device) / win
    y = torch.nn.functional.conv1d(x_1d.abs().view(1,1,-1), w, padding=pad).view(-1)
    if y.numel() > L: y = y[:L]
    elif y.numel() < L: y = torch.nn.functional.pad(y, (0, L - y.numel()), value=y[-1].item())
    return y.clamp_min(1e-6)

def sidechain_gain(env_lin_1d: torch.Tensor, thr_db=-32.0, ratio=6.0):
    env_db = 20*torch.log10(env_lin_1d.clamp_min(1e-6))
    over   = (env_db - thr_db).clamp_min(0.0)
    red_db = over * (1.0 - 1.0/ratio)
    return db_to_lin(-red_db)

def apply_fade(x, sr, fin_s=0.15, fout_s=0.25):
    fin = int(sr*fin_s); fout = int(sr*fout_s)
    y = x.clone()
    if fin>0:
        ramp_in = torch.linspace(0,1,steps=max(1,fin), device=x.device)
        y[..., :fin] *= ramp_in
    if fout>0:
        ramp_out = torch.linspace(1,0,steps=max(1,fout), device=x.device)
        y[..., -fout:] *= ramp_out
    return y

def ensure_stereo(vox, bgm_channels):
    return vox.repeat(2,1) if vox.size(0)==1 and bgm_channels==2 else vox

def tpdf_dither(x, lsb=1.0/32768.0):
    n = (torch.rand_like(x) - 0.5 + torch.rand_like(x) - 0.5) * lsb
    return (x + n).clamp(-1, 1)

def main(args):
    device = "cpu"

    # --- Load ---
    bgm, sr_bgm = torchaudio.load(args.bgm)
    vox, sr_vox = torchaudio.load(args.voice)
    bgm, vox = to_float(bgm), to_float(vox)

    # --- SR unify ---
    target_sr = args.sr
    bgm, _ = resample_if_needed(bgm, sr_bgm, target_sr)
    vox, _ = resample_if_needed(vox, sr_vox, target_sr)

    # --- Length align (shorter) ---
    L = min(bgm.size(-1), vox.size(-1))
    bgm, vox = bgm[..., :L], vox[..., :L]

    # --- VOICE pre (HPF×2 + de-ess + light gate) ---
    vox = torchaudio.functional.highpass_biquad(vox, target_sr, cutoff_freq=args.voice_hpf)
    vox = torchaudio.functional.highpass_biquad(vox, target_sr, cutoff_freq=args.voice_hpf)
    # 라이트 디에서(노치)
    vox = torchaudio.functional.equalizer_biquad(vox, target_sr, center_freq=7500.0, gain=-3.0, Q=2.0)

    if args.gate_enable:
        env_gate = moving_avg_same(vox.mean(dim=0), win=int(target_sr*args.gate_win_ms/1000.0))
        env_db   = 20*torch.log10(env_gate.clamp_min(1e-6))
        under    = (args.gate_thr_db - env_db).clamp_min(0.0)
        gain_db  = -(under / args.gate_ratio).clamp_min(args.gate_floor_db)   # 0 .. floor(neg)
        gain_lin = db_to_lin(gain_db).view(1,-1)
        if vox.size(0)==2: gain_lin = gain_lin.repeat(2,1)
        vox = vox * gain_lin

    # --- BGM pre (HPF×2, LPF×2, 3k -4dB, fade, gain) ---
    bgm = torchaudio.functional.highpass_biquad(bgm, target_sr, cutoff_freq=args.bgm_hpf)
    bgm = torchaudio.functional.highpass_biquad(bgm, target_sr, cutoff_freq=args.bgm_hpf)
    bgm = torchaudio.functional.lowpass_biquad(bgm, target_sr, cutoff_freq=args.bgm_lpf)
    bgm = torchaudio.functional.lowpass_biquad(bgm, target_sr, cutoff_freq=args.bgm_lpf)
    bgm = torchaudio.functional.equalizer_biquad(bgm, target_sr, center_freq=args.eq_center, gain=args.eq_gain_db, Q=args.eq_q)
    bgm = apply_fade(bgm, target_sr, fin_s=args.fade_in_s, fout_s=args.fade_out_s)
    bgm = bgm * args.bgm_gain

    # --- Sidechain envelope (attack/release) ---
    vox_mono = vox.mean(dim=0)
    env   = moving_avg_same(vox_mono, win=int(target_sr*args.attack_ms/1000.0))
    gain  = sidechain_gain(env, thr_db=args.thr_db, ratio=args.ratio)
    gain  = moving_avg_same(gain, win=int(target_sr*args.release_ms/1000.0))
    gain  = gain.clamp(0.05, 1.0)
    gain_st = gain.view(1,-1).repeat(bgm.size(0), 1)

    # --- Align again (safety) ---
    L2 = min(bgm.size(-1), vox.size(-1), gain_st.size(-1))
    bgm, vox, gain_st, env = bgm[..., :L2], vox[..., :L2], gain_st[..., :L2], env[..., :L2]

    # 덕킹
    ducked = bgm * gain_st

    # --- Extra mid duck (≈400 Hz when voice present) ---
    if args.mid_duck_enable and args.mid_max_dip_db > 0.0:
        mid = torchaudio.functional.bandpass_biquad(ducked, target_sr, args.mid_center, Q=args.mid_q)
        rest = ducked - mid
        env_db = 20*torch.log10(env.clamp_min(1e-6))
        alpha = ((env_db - args.thr_db).clamp_min(0.0) / 20.0).clamp(0.0, 1.0)          # 0..1
        extra_dip_db = -args.mid_max_dip_db * alpha                                      # 0..-N dB
        extra_gain = db_to_lin(extra_dip_db).view(1,-1)
        if mid.size(0)==2: extra_gain = extra_gain.repeat(2,1)
        mid_ducked = mid * extra_gain
        ducked = rest + mid_ducked

    # --- Mix ---
    vox = ensure_stereo(vox, bgm_channels=bgm.size(0))
    mix = (vox + ducked).clamp(-1, 1)

    # --- Peak margin ---
    peak = float(mix.abs().max())
    if peak > 0:
        mix = mix/peak * db_to_lin(args.peak_dbfs)   # peak_dbfs is negative (e.g., -1)

    # --- Dither + Save WAV ---
    if args.dither:
        mix = tpdf_dither(mix)
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(out), (mix*32767).short().cpu(), sample_rate=target_sr)
    print(f"[OK] wrote {out}  (len={L2} @ {target_sr} Hz)")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bgm",   required=True)
    ap.add_argument("--voice", required=True)
    ap.add_argument("--out",   required=True)
    # Global
    ap.add_argument("--sr", type=int, default=48000)
    ap.add_argument("--peak_dbfs", type=float, default=-1.0)
    ap.add_argument("--dither", type=int, default=1)
    # Voice
    ap.add_argument("--voice_hpf", type=float, default=80.0)
    ap.add_argument("--gate_enable", type=int, default=1)
    ap.add_argument("--gate_thr_db", type=float, default=-50.0)
    ap.add_argument("--gate_ratio",  type=float, default=1.5)
    ap.add_argument("--gate_floor_db", type=float, default=-12.0)
    ap.add_argument("--gate_win_ms", type=float, default=30.0)
    # BGM
    ap.add_argument("--bgm_gain", type=float, default=0.15)
    ap.add_argument("--bgm_hpf",  type=float, default=70.0)
    ap.add_argument("--bgm_lpf",  type=float, default=12000.0)
    ap.add_argument("--eq_center", type=float, default=3000.0)
    ap.add_argument("--eq_gain_db", type=float, default=-4.0)
    ap.add_argument("--eq_q",     type=float, default=1.1)
    ap.add_argument("--fade_in_s",  type=float, default=0.15)
    ap.add_argument("--fade_out_s", type=float, default=0.25)
    # Sidechain
    ap.add_argument("--thr_db",   type=float, default=-32.0)
    ap.add_argument("--ratio",    type=float, default=6.0)
    ap.add_argument("--attack_ms",type=float, default=50.0)
    ap.add_argument("--release_ms",type=float, default=180.0)
    # Extra mid-duck
    ap.add_argument("--mid_duck_enable", type=int, default=1)
    ap.add_argument("--mid_center",      type=float, default=400.0)
    ap.add_argument("--mid_q",           type=float, default=1.0)
    ap.add_argument("--mid_max_dip_db",  type=float, default=4.0)
    args = ap.parse_args()
    main(args)
