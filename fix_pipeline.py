from pathlib import Path, re

# --- 1) visuals.py: 깨진 토큰(예: ", probe_duration") 제거만 수행 ---
vp = Path('src/visuals.py')
vs = vp.read_text(encoding='utf-8')

# dangling 토큰 제거
vs2 = re.sub(r',\s*probe_duration\b', '', vs)

# ffmpeg run 임포트 라인 정리(있으면 유지, 없으면 추가)
if 'from .utils.ffmpeg import run as ff' not in vs2:
    vs2 = re.sub(r'from\s+\.utils\.ffmpeg\s+import[^\n]*',
                 'from .utils.ffmpeg import run as ff', vs2)
    if 'from .utils.ffmpeg import run as ff' not in vs2:
        vs2 = 'from .utils.ffmpeg import run as ff\n' + vs2

if vs2 != vs:
    vp.write_text(vs2, encoding='utf-8')
    print("✅ visuals.py cleaned")

# --- 2) utils/ffmpeg.py: 런 래퍼로 길이상한/인코더 자동 적용 ---
up = Path('src/utils/ffmpeg.py')
us = up.read_text(encoding='utf-8')

if 'def _preprocess_ffmpeg_cmd' not in us:
    # 기존 run을 _orig_run으로 바꾸고, 새 run을 덧붙임(최초 1회만)
    us2 = us.replace('def run(', 'def _orig_run(', 1)
    us2 += r"""

# === YT PATCH BEGIN ===
import os, re

def _enc_str(fps: int|None):
    enc = os.environ.get("YT_ENCODER","").lower()
    cq  = os.environ.get("YT_CQ","23")
    br  = os.environ.get("YT_VBR","5M")
    mr  = os.environ.get("YT_MAXRATE","8M")
    bs  = os.environ.get("YT_BUFSIZE","16M")
    pre = os.environ.get("YT_NV_PRESET","p5")
    if enc in ("nvenc","h264_nvenc","hevc_nvenc"):
        return f"-c:v h264_nvenc -preset {pre} -rc vbr -cq {cq} -b:v {br} -maxrate {mr} -bufsize {bs}"
    return f"-c:v libx264 -preset veryfast -crf {cq}"

def _clamp_t(cmd: str) -> str:
    try:
        m = float(os.getenv("SHOT_MAX_SEC","0"))
        if m <= 0:
            return cmd
    except:
        return cmd
    # 샷 렌더일 때만(-loop 1 -t X) X를 clamp
    def repl(mt):
        try:
            val = float(mt.group(1))
        except:
            return mt.group(0)
        return f"-loop 1 -t {min(val, m)} "
    return re.sub(r"-loop\s+1\s+-t\s+([0-9]+(?:\.[0-9]+)?)\s+", repl, cmd)

def _inject_enc(cmd: str) -> str:
    # 이미 -c:v가 있으면 놔둠
    if " -c:v " in cmd:
        return cmd
    # mp4 출력 + 필터 사용(샷 렌더 패턴)에만 인코더 주입
    if ".mp4" not in cmd or "-filter_complex" not in cmd:
        return cmd
    # fps 추출(없으면 30 가정)
    fps = 30
    m = re.search(r"\s-r\s+(\d+)", cmd)
    if m:
        try: fps = int(m.group(1))
        except: pass
    enc = _enc_str(fps)
    # filter_complex 바로 뒤에 인코더 플래그 삽입
    cmd = re.sub(r'(-filter_complex\s+"[^"]+")',
                 r'\1 ' + enc + ' -pix_fmt yuv420p -movflags +faststart',
                 cmd, count=1)
    return cmd

def _preprocess_ffmpeg_cmd(cmd: str) -> str:
    if not cmd.strip().startswith("ffmpeg"):
        return cmd
    cmd = _clamp_t(cmd)
    cmd = _inject_enc(cmd)
    return cmd

def run(cmd: str):
    new = _preprocess_ffmpeg_cmd(cmd)
    if new != cmd:
        print(f"[ffmpeg-patch] {new}")
    return _orig_run(new)
# === YT PATCH END ===
"""
    up.write_text(us2, encoding='utf-8')
    print("✅ utils/ffmpeg.py patched")
else:
    print("ℹ️ utils/ffmpeg.py already patched")
