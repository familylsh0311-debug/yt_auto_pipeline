import subprocess, os, json, shlex

def _orig_run(cmd):
    print("[ffmpeg] $", cmd)
    proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        raise RuntimeError(f"ffmpeg error: {proc.stderr[:3000]}")
    return proc

def probe_duration(path):
    cmd = f'ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "{path}"'
    proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        return 0.0
    try:
        return float(proc.stdout.strip())
    except:
        return 0.0


# === YT PATCH BEGIN ===
import os, re


def _fix_symbolic_t(cmd: str) -> str:
    # -loop 1 -t secs  또는  -t {something}  같은 비수치 값을 숫자로 교정
    import os, re
    m = re.search(r'-loop\s+1\s+-t\s+([^\s]+)', cmd)
    if not m:
        return cmd
    tval = m.group(1)
    # 이미 숫자면 그대로
    if re.match(r'^\d+(?:\.\d+)?$', tval):
        return cmd
    # 필터에서 d=프레임수를 찾고, -r FPS 추출
    md = re.search(r'd=(\d+)', cmd)
    mr = re.search(r'\s-r\s+(\d+)', cmd)
    frames = int(md.group(1)) if md else None
    fps = int(mr.group(1)) if mr else 30
    secs = (frames / fps) if frames else 2.0
    # 상한(환경변수) 적용
    try:
        mx = float(os.getenv("SHOT_MAX_SEC", "0"))
        if mx > 0: secs = min(secs, mx)
    except:
        pass
    # 최초 1회만 교체
    return re.sub(r'-loop\s+1\s+-t\s+[^\s]+', f'-loop 1 -t {secs:.2f}', cmd, count=1)

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
    cmd = _fix_symbolic_t(cmd)
    cmd = _clamp_t(cmd)
    cmd = _inject_enc(cmd)
    return cmd

def run(cmd: str):
    new = _preprocess_ffmpeg_cmd(cmd)
    if new != cmd:
        print(f"[ffmpeg-patch] {new}")
    return _orig_run(new)
# === YT PATCH END ===
