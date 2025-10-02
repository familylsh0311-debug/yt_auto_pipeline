import argparse, math
from pathlib import Path
import torch, torchaudio

def db_to_lin(db): return 10.0**(db/20.0)

def ensure_mono(x):
    if x.dim()==1: return x.unsqueeze(0)
    return x if x.size(0)==1 else x.mean(dim=0, keepdim=True)

def resample(x, sr, target_sr):
    return (torchaudio.functional.resample(x, sr, target_sr), target_sr) if sr!=target_sr else (x, sr)

def simple_env(x, sr, win_ms=50):
    # 절대값 -> 이동평균 윈도우 (간단한 RMS 근사)
    win = max(8, int(sr*win_ms/1000))
    w = torch.ones(1,1,win, device=x.device)/win
    # mono로
    m = ensure_mono(x)
    y = torch.nn.functional.conv1d(m.abs().unsqueeze(0), w, padding=win//2).squeeze(0).squeeze(0)
    return y.clamp_min(1e-6)

def sidechain_gain(env, thr_db=-32.0, ratio=6.0):
    # env: 0~1 선형 -> dB
    env_db = 20*torch.log10(env.clamp_min(1e-6))
    over = (env_db - thr_db).clamp_min(0.0)
    red_db = over * (1.0 - 1.0/ratio)
    gain = db_to_lin(-red_db)
    return gain

def main(args):
    device="cpu"
    # load
    bgm, sr_bgm = torchaudio.load(args.bgm)
    vox, sr_vox = torchaudio.load(args.voice)
    # to float -1..1
    bgm = bgm.float()/32768.0 if bgm.dtype==torch.int16 else bgm.float()
    vox = vox.float()/32768.0 if vox.dtype==torch.int16 else vox.float()

    # resample 48k
    target_sr=48000
    bgm, _ = resample(bgm, sr_bgm, target_sr)
    vox, _ = resample(vox, sr_vox, target_sr)

    # 길이 맞추기(짧은 것 기준)
    L = min(bgm.size(-1), vox.size(-1))
    bgm = bgm[..., :L]
    vox = vox[..., :L]

    # BGM 전처리: HPF/LPF + 3kHz -4dB 컷 + 볼륨
    bgm = torchaudio.functional.highpass_biquad(bgm, target_sr, cutoff_freq=70.0)
    bgm = torchaudio.functional.lowpass_biquad(bgm, target_sr, cutoff_freq=12000.0)
    bgm = torchaudio.functional.equalizer_biquad(bgm, target_sr, center_freq=3000.0, gain=-4.0, Q=1.1)
    bgm = bgm * 0.15

    # 사이드체인: 보이스 에너지 -> BGM 게인
    env = simple_env(vox, target_sr, win_ms=50)
    gain = sidechain_gain(env, thr_db=-32.0, ratio=6.0)  # 필요시 thr/ratio 조절
    # 스무딩(릴리즈 200ms 근사): 추가 200ms LPF
    g2 = simple_env(gain.unsqueeze(0), target_sr, win_ms=200)
    g2 = g2.clamp(0.05, 1.0)
    gain_st = g2.unsqueeze(0)  # (1, L)
    if bgm.size(0)>1:
        gain_st = gain_st.repeat(bgm.size(0),1)  # 스테레오 동일 게인

    ducked = bgm * gain_st

    # 합치기
    # 내레이션은 모노면 스테레오로 확장(중앙에 배치)
    if vox.size(0)==1 and ducked.size(0)==2:
        vox = vox.repeat(2,1)
    mix = (vox + ducked).clamp(-1,1)

    # 피크 -1 dBFS로 살짝 여유
    peak = mix.abs().max().item()
    if peak>0: mix = mix/peak * db_to_lin(-1.0)

    # 저장(WAV)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(out), (mix*32767).short().cpu(), sample_rate=target_sr)
    print(f"[OK] wrote {out}")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--bgm", required=True)
    p.add_argument("--voice", required=True)
    p.add_argument("--out", required=True)
    args=p.parse_args()
    main(args)
