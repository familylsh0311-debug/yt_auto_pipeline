#!/usr/bin/env bash
set -Eeuo pipefail

# ===== 기본값 =====
VIDEO="${VIDEO:-out/shorts_30s/final.mp4}"
OUTDIR="${OUTDIR:-out/shorts_30s}"
GAIN="${GAIN:-0.15}"
THR="${THR:- -32}"
RATIO="${RATIO:-6}"
ATTACK="${ATTACK:-50}"
RELEASE="${RELEASE:-180}"
VOICE="${VOICE:-}"
BGM="${BGM:-}"
DIR="${DIR:-}"
ALL="${ALL:-0}"
LUFS14="${LUFS14:-0}"
VARIANTS="${VARIANTS:-0}"       # 1이면 mild/std/strong 3가지 버전 생성
MID_DIP="${MID_DIP:-4}"         # 중역 추가 덕킹 최대 dB (기본 4dB)

usage() {
  cat <<USG
Usage: ./oneclick_mix.sh [옵션]
  --video=PATH   입력 영상 (기본: out/shorts_30s/final.mp4)
  --voice=PATH   내레이션 오디오(미지정시 영상에서 추출)
  --bgm=PATH     BGM 파일 직접 지정
  --dir=PATH     생성 폴더 지정(미지정시 최신 폴더)
  --gain=FLOAT   BGM 게인 (기본 0.15)
  --thr=DB       덕킹 스레시홀드 dB (기본 -32, 강하게 -35)
  --ratio=N      덕킹 레시오 (기본 6, 강하게 8)
  --attack=MS    공격 ms (기본 50)
  --release=MS   릴리즈 ms (기본 180)
  --mid-dip=DB   중역 추가 덕킹 최대 dB (기본 4)
  --all          폴더 내 모든 트랙 배치 처리
  --variants     mild/std/strong 3개 버전 자동 생성
  --lufs14       최종 영상 -14 LUFS 정규화
  -h|--help      도움말
USG
}

for arg in "$@"; do
  case "$arg" in
    --video=*)   VIDEO="${arg#*=}";;
    --voice=*)   VOICE="${arg#*=}";;
    --bgm=*)     BGM="${arg#*=}";;
    --dir=*)     DIR="${arg#*=}";;
    --gain=*)    GAIN="${arg#*=}";;
    --thr=*)     THR="${arg#*=}";;
    --ratio=*)   RATIO="${arg#*=}";;
    --attack=*)  ATTACK="${arg#*=}";;
    --release=*) RELEASE="${arg#*=}";;
    --mid-dip=*) MID_DIP="${arg#*=}";;
    --all)       ALL=1;;
    --variants)  VARIANTS=1;;
    --lufs14)    LUFS14=1;;
    -h|--help)   usage; exit 0;;
    *) echo "[WARN] unknown option: $arg";;
  esac
done

mkdir -p "$OUTDIR"

# venv
if [[ -d .venv310 ]]; then source .venv310/bin/activate || true; fi

# 필요 툴 체크
[[ -f mix_duck_v4.py ]] || { echo "[ERR] mix_duck_v4.py 없음"; exit 1; }
command -v ffmpeg >/dev/null || { echo "[ERR] ffmpeg 미설치"; exit 1; }

# VOICE
VOICE_WAV=""
if [[ -n "$VOICE" ]]; then
  [[ -f "$VOICE" ]] || { echo "[ERR] --voice 파일 없음: $VOICE"; exit 1; }
  VOICE_WAV="$VOICE"
else
  [[ -f "$VIDEO" ]] || { echo "[ERR] 영상 없음: $VIDEO"; exit 1; }
  VOICE_WAV="$OUTDIR/voice.wav"
  echo "[INFO] extract voice → $VOICE_WAV"
  ffmpeg -y -i "$VIDEO" -vn -ac 1 -ar 48000 "$VOICE_WAV" >/dev/null 2>&1
  echo "[INFO] loudnorm voice → $OUTDIR/voice_norm.wav"
  ffmpeg -y -i "$VOICE_WAV" -filter:a loudnorm=I=-14:TP=-1.5:LRA=9 "$OUTDIR/voice_norm.wav" >/dev/null 2>&1
  VOICE_WAV="$OUTDIR/voice_norm.wav"
fi

select_bgm_from_dir() {
  local d="$1"
  shopt -s nullglob
  if [[ -f "${d%/}/bgm_best.wav" ]]; then echo "${d%/}/bgm_best.wav"; return; fi
  local first=""
  for f in "${d%/}/"*.wav "${d%/}/"*.mp3; do first="$f"; break; done
  echo "$first"
}

# BGM
if [[ -z "$BGM" ]]; then
  if [[ -n "$DIR" ]]; then
    [[ -d "$DIR" ]] || { echo "[ERR] --dir 폴더 없음: $DIR"; exit 1; }
    BGM="$(select_bgm_from_dir "$DIR")"
  else
    LATEST_DIR=$(ls -1dt assets/bgm_30s/*/ 2>/dev/null | head -n1 || true)
    [[ -n "$LATEST_DIR" ]] || { echo "[ERR] 생성 폴더 없음: assets/bgm_30s/*/"; exit 1; }
    echo "[INFO] latest bgm dir: $LATEST_DIR"
    BGM="$(select_bgm_from_dir "$LATEST_DIR")"
  fi
fi
[[ -n "$BGM" && -f "$BGM" ]] || { echo "[ERR] BGM을 찾지 못했습니다."; exit 1; }

echo "[INFO] BGM:   $BGM"
echo "[INFO] VOICE: $VOICE_WAV"

process_one() {
  local bgm="$1"
  local stem; stem="$(basename "${bgm%.*}")"
  local mix_wav="$OUTDIR/mix_${stem}.wav"
  local mix_m4a="$OUTDIR/mix_${stem}.m4a"
  local out_mp4="$OUTDIR/final_ducked_${stem}.mp4"

  python mix_duck_v4.py \
    --bgm "$bgm" --voice "$VOICE_WAV" --out "$mix_wav" \
    --bgm_gain "$GAIN" --thr_db "$THR" --ratio "$RATIO" \
    --attack_ms "$ATTACK" --release_ms "$RELEASE" \
    --mid_max_dip_db "$MID_DIP"

  ffmpeg -y -i "$mix_wav" -c:a aac -b:a 192k "$mix_m4a" >/dev/null 2>&1
  ffmpeg -y -i "$VIDEO" -i "$mix_m4a" -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k -shortest "$out_mp4" >/dev/null 2>&1

  if [[ "$LUFS14" == "1" ]]; then
    local norm_mp4="${out_mp4%.mp4}_loudnorm.mp4"
    ffmpeg -y -i "$out_mp4" -filter:a loudnorm=I=-14:TP=-1.5:LRA=9 -c:v copy -c:a aac -b:a 192k "$norm_mp4" >/dev/null 2>&1
    echo "[OK] $norm_mp4"
  else
    echo "[OK] $out_mp4"
  fi
}

process_variants() {
  local bgm="$1"
  local stem; stem="$(basename "${bgm%.*}")"
  declare -a names=("mild" "std" "strong")
  declare -a thrs=("$THR" "$THR" "-35")
  declare -a ratios=("$RATIO" "$RATIO" "8")
  for i in "${!names[@]}"; do
    local tag="${names[$i]}"
    local mix_wav="$OUTDIR/mix_${stem}_${tag}.wav"
    local mix_m4a="$OUTDIR/mix_${stem}_${tag}.m4a"
    local out_mp4="$OUTDIR/final_ducked_${stem}_${tag}.mp4"
    python mix_duck_v4.py \
      --bgm "$bgm" --voice "$OUTDIR/voice_norm.wav" --out "$mix_wav" \
      --bgm_gain "$GAIN" --thr_db "${thrs[$i]}" --ratio "${ratios[$i]}" \
      --attack_ms "$ATTACK" --release_ms "$RELEASE" \
      --mid_max_dip_db "$MID_DIP"
    ffmpeg -y -i "$mix_wav" -c:a aac -b:a 192k "$mix_m4a" >/dev/null 2>&1
    ffmpeg -y -i "$VIDEO" -i "$mix_m4a" -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k -shortest "$out_mp4" >/dev/null 2>&1
    [[ "$LUFS14" == "1" ]] && ffmpeg -y -i "$out_mp4" -filter:a loudnorm=I=-14:TP=-1.5:LRA=9 -c:v copy -c:a aac -b:a 192k "${out_mp4%.mp4}_loudnorm.mp4" >/dev/null 2>&1
    echo "[OK] $out_mp4"
  done
}

if [[ "$ALL" == "1" ]]; then
  SRC_DIR="${DIR:-$(dirname "$BGM")}"
  echo "[INFO] batch in: $SRC_DIR"
  shopt -s nullglob
  files=( "$SRC_DIR"/*.wav "$SRC_DIR"/*.mp3 )
  [[ ${#files[@]} -gt 0 ]] || { echo "[ERR] 배치 대상 없음"; exit 1; }
  for f in "${files[@]}"; do
    echo "---- [BGM] $f"
    [[ "$VARIANTS" == "1" ]] && process_variants "$f" || process_one "$f"
  done
else
  [[ "$VARIANTS" == "1" ]] && process_variants "$BGM" || process_one "$BGM"
fi

echo "[DONE]"
