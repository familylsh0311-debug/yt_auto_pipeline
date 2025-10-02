import torch, torchaudio
from einops import rearrange
from stable_audio_tools import get_pretrained_model
from stable_audio_tools.inference.generation import generate_diffusion_cond

device = "cuda" if torch.cuda.is_available() else "cpu"
model, cfg = get_pretrained_model("stabilityai/stable-audio-open-1.0")
model = model.to(device)

conditioning = [{
  "prompt": "instrumental only, no vocals, lofi chillhop, warm Rhodes and soft drums, simple repeating motif, clean mix, 90 BPM",
  "seconds_start": 0, "seconds_total": 30
}]

audio = generate_diffusion_cond(
  model, steps=100, cfg_scale=7, conditioning=conditioning,
  sample_size=cfg["sample_size"], sigma_min=0.3, sigma_max=500,
  sampler_type="dpmpp-3m-sde", device=device
)
audio = rearrange(audio, "b d n -> d (b n)")
audio = audio.float(); audio = audio/(audio.abs().max()+1e-8)
audio = (audio.clamp(-1,1)*32767).short().cpu()
torchaudio.save("assets/bgm_seed.wav", audio, cfg["sample_rate"])
print("Wrote assets/bgm_seed.wav")
