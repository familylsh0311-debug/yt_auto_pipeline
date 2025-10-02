import re, os, json, math, random, time, textwrap, jinja2, yaml

TIME_RE = re.compile(r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2}),(?P<ms>\d{3})")

def load_template(path, **kw):
    with open(path, "r", encoding="utf-8") as f:
        tpl = jinja2.Template(f.read())
    return tpl.render(**kw)

def synthesize_script_from_topic(topic: str, lang: str, prompt_path: str):
    prompt = load_template(prompt_path, topic=topic)
    title = f"{topic} 핵심만 1분 정리"
    body = textwrap.dedent(f"""
    # 제목
    {title}

    # 개요
    {topic}에 대해 꼭 알아야 할 포인트를 1분 안에 정리합니다.

    # 본문
    1) 왜 중요한가: 현실 속 예시로 핵심을 설명합니다.
    2) 핵심 3가지: 한 문장 요약 + 짧은 예시.
    3) 실전 팁: 바로 써먹을 수 있는 행동 1~2개.

    # 마무리
    도움이 되셨다면 구독/좋아요 눌러주세요!

    # 해시태그
    #{topic.replace(' ', '')} #요약 #꿀팁
    """).strip()
    return body

def _time_to_secs(t: str) -> float:
    m = TIME_RE.match(t.strip())
    if not m: return 0.0
    d = m.groupdict()
    h = int(d["h"]); mi = int(d["m"]); s = int(d["s"]); ms = int(d["ms"])
    return h*3600 + mi*60 + s + ms/1000.0

def _detect_mode(text: str) -> str:
    # SRT?
    if "-->" in text and TIME_RE.search(text):
        return "srt"
    # JSON?
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return "json"
    except Exception:
        pass
    # Markdown-ish?
    if re.search(r"^#{1,3}\s+.+", text, flags=re.M):
        return "md"
    return "txt"

def _extract_directives(block: str):
    # [[PROMPT: ...]], [[DUR: 4.5]]
    prompt = None
    dur = None
    def repl(m):
        nonlocal prompt, dur
        key = m.group(1).strip().upper()
        val = m.group(2).strip()
        if key == "PROMPT": prompt = val
        elif key in ("DUR","SECS","DURATION"):
            try: dur = float(val)
            except: pass
        return ""
    cleaned = re.sub(r"\[\[\s*(PROMPT|DUR|SECS|DURATION)\s*:\s*(.*?)\s*\]\]", repl, block)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, prompt, dur

def parse_srt(text: str):
    # Very small SRT parser
    entries = []
    cur = {"i":None,"start":None,"end":None,"lines":[]}
    for line in text.splitlines():
        line=line.strip("\ufeff").rstrip()
        if not line:
            # flush
            if cur["i"] is not None and cur["start"] and cur["end"]:
                t = "\n".join(cur["lines"]).strip()
                t, prompt, dur_override = _extract_directives(t)
                dur = _time_to_secs(cur["end"]) - _time_to_secs(cur["start"])
                if dur_override: dur = dur_override
                entries.append({"text": t, "prompt": prompt or f"cinematic, high detail, key idea: {t}",
                                "secs": max(0.5, round(dur,2))})
            cur = {"i":None,"start":None,"end":None,"lines":[]}
            continue
        if cur["i"] is None and line.isdigit():
            cur["i"] = int(line)
            continue
        if cur["start"] is None and "-->" in line:
            a, b = [s.strip() for s in line.split("-->")]
            cur["start"], cur["end"] = a, b
            continue
        cur["lines"].append(line)
    # last flush
    if cur["i"] is not None and cur["start"] and cur["end"]:
        t = "\n".join(cur["lines"]).strip()
        t, prompt, dur_override = _extract_directives(t)
        dur = _time_to_secs(cur["end"]) - _time_to_secs(cur["start"])
        if dur_override: dur = dur_override
        entries.append({"text": t, "prompt": prompt or f"cinematic, high detail, key idea: {t}",
                        "secs": max(0.5, round(dur,2))})
    return entries

def parse_json(text: str):
    arr = json.loads(text)
    shots = []
    for it in arr:
        t = (it.get("text") or "").strip()
        p = it.get("prompt")
        d = it.get("secs") or it.get("dur")
        if not p: p = f"cinematic, high detail, key idea: {t}"
        if d: d = float(d)
        shots.append({"text": t, "prompt": p, "secs": d})
    return shots

def parse_md_or_txt(text: str, target_secs=70, min_shots=6, max_shots=10):
    # Split on headings ### or ## or #, or bullet points, otherwise sentences/paragraphs
    blocks = []
    # Prefer headings as shot boundaries
    headings = re.split(r"(?m)^#{1,3}\s+", text)
    if len(headings) > 1:
        # first split part may be preface; ignore if empty
        for h in headings[1:]:
            # take first line as title, rest as body
            lines = h.splitlines()
            if not lines: continue
            b = "\n".join(lines[1:]).strip() or lines[0].strip()
            blocks.append(b)
    else:
        # bullet lines or paragraphs
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for ln in lines:
            blocks.append(ln)

    # Extract directives and clean text
    cleaned = []
    for b in blocks:
        t, p, d = _extract_directives(b)
        cleaned.append({"text": t, "prompt": p, "secs": d})

    # Bound number of shots
    n = max(min_shots, min(max_shots, len(cleaned) if cleaned else 6))
    if len(cleaned) < n:
        # pad by splitting long sentences
        pads = []
        for c in cleaned:
            parts = re.split(r"[,.;] ", c["text"])
            for pp in parts:
                pp = pp.strip()
                if pp: pads.append({"text": pp, "prompt": None, "secs": None})
        cleaned = (cleaned + pads)[:n]
    else:
        cleaned = cleaned[:n]

    base = target_secs / n
    shots = []
    for c in cleaned:
        t = c["text"].strip()
        p = c["prompt"] or f"cinematic, high detail, trending artstyle, key idea: {t}"
        d = c["secs"] if c["secs"] else max(3.0, base * random.uniform(0.9, 1.2))
        shots.append({"text": t, "prompt": p, "secs": round(d, 2)})
    return shots

def parse_script(script_text: str, mode: str="auto", target_secs=70, min_shots=6, max_shots=10):
    if mode == "auto":
        mode = _detect_mode(script_text)
    if mode == "srt":
        return parse_srt(script_text)
    if mode == "json":
        return parse_json(script_text)
    if mode in ("md","markdown"):
        return parse_md_or_txt(script_text, target_secs, min_shots, max_shots)
    # default plain text
    return parse_md_or_txt(script_text, target_secs, min_shots, max_shots)

# Backward-compatible helper
def split_into_shots(script_text: str, target_secs=70, min_shots=6, max_shots=10):
    return parse_md_or_txt(script_text, target_secs, min_shots, max_shots)
