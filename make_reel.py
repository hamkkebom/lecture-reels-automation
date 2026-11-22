#!/usr/bin/env python
"""강의 촬영본 -> 인스타 릴스 (승리어학원 @victory.edu.english 스타일).

파이프라인: 무음 컷 -> 9:16 (1080x1920) -> 음성 인식(Whisper) -> 상단 2줄 제목 +
하단 강조 자막 -> 음량 보정 + 릴스 규격 내보내기 -> 규격 검사 + 확인용 시트.

실행 (프로젝트 폴더에서):
  .venv\\Scripts\\python make_reel.py 원본.mp4 --title1 "내신 필수 동명사 어휘" ^
      --title2 "\\"MEGAFASE + α\\"" --highlight 동명사 --highlight MEGAFASE:red

자막을 고친 뒤 다시 입히기 (음성 인식 생략):
  .venv\\Scripts\\python make_reel.py 원본.mp4 --title1 ... --srt work\\원본\\captions.srt
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILL = ROOT / ".claude" / "skills" / "ffmpeg-skill" / "scripts"

W, H = 1080, 1920

TIMINGS: list[tuple[str, float]] = []  # (단계, 초) 병목 파악용

# RRGGBB
COLORS = {
    "white": "FFFFFF",
    "yellow": "FFD400",
    "orange": "FF8A1F",
    "red": "FF3B30",
    "green": "3DDC5A",
    "blue": "4DA3FF",
    "pink": "FF5FA2",
    "mint": "5CE1C6",
}


# ---------------------------------------------------------------- helpers
def tool_env() -> dict:
    """winget으로 설치한 최신 FFmpeg를 PATH 맨 앞에 둔다.

    이 PC의 시스템 PATH에는 AutoPod에 딸린 2023년 빌드가 먼저 잡혀 있어서,
    그대로 두면 새로 설치한 버전이 쓰이지 않는다.
    """
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    pkgs = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    bins = sorted(pkgs.glob("Gyan.FFmpeg*/ffmpeg-*/bin")) if pkgs.is_dir() else []
    if bins:
        env["PATH"] = str(bins[-1]) + os.pathsep + env.get("PATH", "")
    return env


def run_tool(name: str, *args: str, capture: bool = False) -> dict | None:
    """ffmpeg-skill 스크립트 하나를 실행한다. 실패하면 그대로 중단."""
    cmd = [sys.executable, str(SKILL / f"{name}.py"), *[str(a) for a in args]]
    env = tool_env()
    print(f"\n[{name}] {' '.join(str(a) for a in args)}", flush=True)
    t0 = time.time()
    proc = subprocess.run(cmd, env=env, capture_output=capture, text=True, encoding="utf-8")
    TIMINGS.append((name, round(time.time() - t0, 1)))
    if proc.returncode != 0:
        if capture:
            sys.stderr.write((proc.stdout or "") + (proc.stderr or ""))
        raise SystemExit(f"[{name}] 실패 (exit {proc.returncode})")
    if capture:
        out = proc.stdout
        start = out.find("{")
        return json.loads(out[start:]) if start >= 0 else None
    return None


def ass_color(name_or_hex: str) -> str:
    rgb = COLORS.get(name_or_hex.lower(), name_or_hex).lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", rgb):
        raise SystemExit(f"알 수 없는 색: {name_or_hex} (사용 가능: {', '.join(COLORS)} 또는 RRGGBB)")
    return f"&H{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}&".upper()


def ass_time(t: float) -> str:
    cs = max(0, round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def srt_time(t: float) -> str:
    ms = max(0, round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def esc(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def save_timings(work: Path, stage: str) -> None:
    """단계별 걸린 시간을 work/<이름>/timing_<stage>.json 에 남기고 화면에도 보여 준다."""
    total: dict[str, float] = {}
    for name, sec in TIMINGS:
        total[name] = round(total.get(name, 0) + sec, 1)
    (work / f"timing_{stage}.json").write_text(json.dumps(total, ensure_ascii=False, indent=1), encoding="utf-8")
    print("단계별 시간(초): " + ", ".join(f"{k} {v}" for k, v in total.items()))


# ------------------------------------------------------------- transcribe
def add_cuda_dlls() -> None:
    """pip로 설치한 NVIDIA 라이브러리(cublas/cudnn)를 Windows DLL 검색 경로에 넣는다."""
    base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not base.is_dir():
        return
    for d in base.glob("*/bin"):
        os.add_dll_directory(str(d))
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")


def load_audio_16k(media: Path, work: Path):
    """영상의 소리를 16kHz 모노 float32 배열로 읽는다 (faster-whisper 내장 디코더를 거치지 않음)."""
    import wave

    import numpy as np

    wav = work / "audio_16k.wav"
    run_tool("audio", media, "-o", wav, "--sample-rate", 16000, "--overwrite")
    with wave.open(str(wav), "rb") as f:
        if f.getsampwidth() != 2 or f.getframerate() != 16000:
            raise SystemExit(f"예상과 다른 WAV 형식: {f.getsampwidth() * 8}bit {f.getframerate()}Hz")
        data = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
        ch = f.getnchannels()
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return (data / 32768.0).astype(np.float32)


def transcribe(media: Path, work: Path, model_name: str, language: str, prompt: str, device: str) -> list[dict]:
    audio = load_audio_16k(media, work)
    add_cuda_dlls()
    from faster_whisper import WhisperModel

    attempts = [("cuda", "float16"), ("cpu", "int8")] if device == "auto" else [
        (device, "float16" if device == "cuda" else "int8")]
    last_err: Exception | None = None
    for dev, ctype in attempts:
        try:
            print(f"\n[whisper] {model_name} / {dev} / {ctype}", flush=True)
            model = WhisperModel(model_name, device=dev, compute_type=ctype)
            segments, _info = model.transcribe(
                audio, language=language, word_timestamps=True, vad_filter=True,
                initial_prompt=prompt or None, condition_on_previous_text=False)
            words = []
            for seg in segments:
                for w in seg.words or []:
                    txt = w.word.strip()
                    if txt:
                        words.append({"start": float(w.start), "end": float(w.end), "text": txt})
            return words
        except Exception as e:  # GPU 라이브러리 문제면 CPU로 한 번 더
            last_err = e
            print(f"[whisper] {dev} 실패: {e}", flush=True)
    raise SystemExit(f"음성 인식 실패: {last_err}")


# 자막 줄을 끊을 말끝. STRONG은 문장이 끝나는 어미, WEAK는 절이 이어지는 어미.
STRONG_END = re.compile(
    r"(요|죠|니다|까|야|잖아|거든|봐|겠네|리네|해|돼|있어|없어|했어|됐어|나왔어|같아|않아|맞아|가까워"
    r"|들어가|쓸게|볼게|할게|그치|그렇지|겠지|되지|하지|한다고|간다|된다|이다|한다|말라는 얘기야)$")
NOT_END = re.compile(r"(해야|써야|줘야|봐야|가야|와야|되어야|돼야|어떻게 해|못 해)$")
WEAK_END = re.compile(r"(는데|은데|니까|으면|되면|라면|다면|고요|구요|지만|때는|때|보면|해서|아서|어서)$")


def words_to_cues(words: list[dict], max_chars: int, max_gap: float) -> list[dict]:
    """단어 타이밍 -> 한 줄짜리 짧은 자막 큐."""
    cues: list[dict] = []
    cur: list[dict] = []

    def flush() -> None:
        if cur:
            text = " ".join(w["text"] for w in cur)
            if text:
                cues.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": text})
            cur.clear()

    for w in words:
        if cur:
            so_far = len(" ".join(x["text"] for x in cur))
            if so_far + 1 + len(w["text"]) > max_chars or w["start"] - cur[-1]["end"] > max_gap:
                flush()
        cur.append(w)
        text = " ".join(x["text"] for x in cur)
        # 문장 끝에서는 항상, 쉼표에서는 줄이 어느 정도 찼을 때 끊는다.
        # 강의 말투는 마침표 없이 이어져서, 말끝(어미)으로도 끊는다.
        tok = w["text"].rstrip(",")
        if re.search(r"[.?!]$", w["text"]) or (w["text"].endswith(",") and len(text) >= 8):
            flush()
        elif len(text) >= 7 and STRONG_END.search(tok) and not NOT_END.search(tok):
            flush()
        elif len(text) >= 12 and WEAK_END.search(tok):
            flush()
    flush()

    # 한두 글자짜리 꼬리 줄은 바로 앞 줄에 붙인다 (말이 이어질 때만).
    merged: list[dict] = []
    for c in cues:
        prev = merged[-1] if merged else None
        if (prev and len(c["text"]) <= 4 and c["start"] - prev["end"] < 0.3
                and not re.search(r"[.?!]$", prev["text"]) and len(prev["text"]) + 1 + len(c["text"]) <= max_chars + 5):
            prev["text"] += " " + c["text"]
            prev["end"] = c["end"]
        else:
            merged.append(c)
    cues = merged
    for c in cues:  # 줄 끝의 마침표·쉼표는 화면에 넣지 않는다 (물음표·느낌표는 둔다)
        c["text"] = re.sub(r"[.,。]+$", "", c["text"]).strip()
    cues = [c for c in cues if c["text"]]

    # 화면에 잠깐이라도 머물도록 끝을 조금 늘리되 다음 자막과 겹치지 않게 한다.
    for i, c in enumerate(cues):
        nxt = cues[i + 1]["start"] if i + 1 < len(cues) else c["end"] + 1.0
        c["end"] = max(c["end"], min(c["end"] + 0.25, nxt - 0.02))
        if c["end"] - c["start"] < 0.6:
            c["end"] = min(c["start"] + 0.6, nxt - 0.02)
    return cues


def write_srt(cues: list[dict], path: Path) -> None:
    lines = []
    for i, c in enumerate(cues, 1):
        lines += [str(i), f"{srt_time(c['start'])} --> {srt_time(c['end'])}", c["text"], ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def read_srt(path: Path) -> list[dict]:
    cues = []
    blocks = re.split(r"\r?\n\s*\r?\n", path.read_text(encoding="utf-8-sig").strip())
    pat = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
    for b in blocks:
        rows = [r for r in b.splitlines() if r.strip()]
        for i, r in enumerate(rows):
            m = pat.search(r)
            if m:
                g = [int(x) for x in m.groups()]
                start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                text = " ".join(rows[i + 1:]).strip()
                if text:
                    cues.append({"start": start, "end": end, "text": text})
                break
    return cues


# -------------------------------------------------------------------- ASS
def glyph_width(text: str, size: int) -> float:
    """화면 폭 추정 (Pretendard ExtraBold 기준 근사). 제목이 화면을 넘지 않게 줄이는 데 쓴다."""
    w = 0.0
    for ch in text:
        if ch == " ":
            w += 0.20
        elif ord(ch) >= 0x1100:
            w += 0.70
        else:
            w += 0.44
    return w * size


def title_markup(text: str, color: str, all_highlight: bool) -> str:
    """제목 한 줄. *별표* 로 감싼 부분만 강조색 기울임. 별표가 없고 all_highlight면 줄 전체 강조."""
    on = f"{{\\1c{ass_color(color)}\\i1}}"
    off = "{\\1c&HFFFFFF&\\i0}"
    if "*" in text:
        # 조각마다 앞뒤 공백을 지우면 "*Neither* of" 가 "Neitherof" 로 붙으므로 공백은 그대로 둔다.
        parts = [p.replace("{", "(").replace("}", ")") for p in text.strip().split("*")]
        return "".join((on + p + off) if i % 2 else p for i, p in enumerate(parts))
    return on + esc(text) if all_highlight else esc(text)


def caption_spans(text: str, highlights: list[tuple[str, str]], english_color: str | None) -> list[tuple[int, int, str, bool]]:
    """(시작, 끝, 색, 기울임) 목록. 강조 단어가 먼저, 영어 단어는 남는 자리에."""
    spans: list[tuple[int, int, str, bool]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= s or a >= e for s, e, _c, _i in spans)

    for word, color in sorted(highlights, key=lambda h: -len(h[0])):
        for m in re.finditer(re.escape(esc(word)), text, flags=re.IGNORECASE):
            if free(m.start(), m.end()):
                spans.append((m.start(), m.end(), color, False))
    if english_color:
        for m in re.finditer(r"[A-Za-z][A-Za-z'\-]*(?:\s*[+\s]\s*-?[A-Za-z][A-Za-z'\-]*)*", text):
            if free(m.start(), m.end()):
                spans.append((m.start(), m.end(), english_color, True))
    return sorted(spans)


def caption_body(text: str, spans: list[tuple[int, int, str, bool]], dur: float, typewriter: bool) -> str:
    """색 입힌 자막 한 줄. typewriter면 글자가 하나씩 나타난다."""
    n = sum(1 for ch in text if ch != " ")
    step = min(0.07, dur * 0.5 / max(n, 1)) if typewriter else 0.0
    out: list[str] = []
    state = ("white", False)
    k = 0
    for i, ch in enumerate(text):
        cur = ("white", False)
        for s, e, color, italic in spans:
            if s <= i < e:
                cur = (color, italic)
                break
        tags = ""
        if cur != state:
            tags += f"\\1c{ass_color(cur[0])}\\i{1 if cur[1] else 0}"
            state = cur
        if ch != " ":
            if step and k:
                ms = round(k * step * 1000)
                tags += f"\\alpha&HFF&\\t({ms},{ms + 1},\\alpha&H00&)"
            k += 1
        out.append((f"{{{tags}}}" if tags else "") + ch)
    return "".join(out)


def pop_events(words: list[dict], duration: float, a: argparse.Namespace) -> list[str]:
    """숏폼식 자막: 2~3단어씩 크게 띄우고, 말하는 순간의 단어를 키우면서 색을 바꾼다."""
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        if w["start"] >= duration:
            break
        if cur:
            length = len(" ".join(x["text"] for x in cur)) + 1 + len(w["text"])
            if len(cur) >= 3 or length > 12 or w["start"] - cur[-1]["end"] > 0.4:
                chunks.append(cur)
                cur = []
        cur.append(w)
        tok = w["text"].rstrip(",")
        if re.search(r"[.?!,]$", w["text"]) or (STRONG_END.search(tok) and not NOT_END.search(tok)):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)

    ev = []
    for i, ch in enumerate(chunks):
        start = ch[0]["start"]
        nxt = chunks[i + 1][0]["start"] if i + 1 < len(chunks) else duration
        end = min(max(ch[-1]["end"] + 0.3, start + 0.45), nxt - 0.01, duration)
        if end <= start:
            continue
        parts = []
        for j, w in enumerate(ch):
            text = esc(re.sub(r"[.,。]+$", "", w["text"]))
            if not text:
                continue
            base = "white"
            for term, color in sorted(a.hl, key=lambda h: -len(h[0])):
                if term.replace(" ", "") in text.replace(" ", "") or text in term.split():
                    base = color
                    break
            else:
                if a.english_color and re.search(r"[A-Za-z]{2,}", text) or (a.english_color and text.lower() in ("i", "a")):
                    base = a.english_color
            active = a.pop_active if base == "white" else base
            on = round((w["start"] - start) * 1000)
            off = round(((ch[j + 1]["start"] if j + 1 < len(ch) else end) - start) * 1000)
            parts.append(
                f"{{\\1c{ass_color(base)}\\fscx100\\fscy100"
                f"\\t({on},{on + 70},\\1c{ass_color(active)}\\fscx114\\fscy114)"
                f"\\t({off},{off + 70},\\1c{ass_color(base)}\\fscx100\\fscy100)}}{text}")
        if parts:
            ev.append(f"Dialogue: 3,{ass_time(start)},{ass_time(end)},Pop,,0,0,0,,"
                      f"{{\\pos({W // 2},{a.pop_y})\\fad(60,0)}}" + " ".join(parts))
    return ev


def build_ass(cues: list[dict], duration: float, a: argparse.Namespace, band: tuple[int, int] | None,
              pop_words: list[dict] | None = None) -> str:
    """band: 레터박스일 때 영상이 놓인 (위, 아래) y좌표. 세로 꽉 찬 화면이면 None."""
    plain = [re.sub(r"\*", "", t) for t in (a.title1, a.title2) if t]
    size = a.title_size
    for t in plain:  # 가장 긴 줄이 화면 폭의 90%를 넘지 않게
        w = glyph_width(t, size)
        if w > W * 0.9:
            size = int(size * W * 0.9 / w)
    gap = round(size * 1.12)

    if band:  # 제목은 영상 바로 위 검은 띠, 자막은 바로 아래 띠
        top, bottom = band
        t_an, cap_an = 2, 8
        last_y, cap_y = top - 55, bottom + 50
        ys = [last_y - gap, last_y] if len(plain) == 2 else [last_y]
    else:
        t_an, cap_an = 8, 2
        ys, cap_y = [a.title_y, a.title_y + gap], a.caption_y

    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,{a.font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,0,{t_an},20,20,0,1
Style: Glow,{a.font},{size},&HFF000000,&HFF000000,&H50000000,&H50000000,-1,0,0,0,100,100,0,0,1,10,0,{t_an},20,20,0,1
Style: CapBox,{a.font},{a.caption_size},&HFFFFFFFF,&HFFFFFFFF,&H{a.box_alpha}000000,&H{a.box_alpha}000000,-1,0,0,0,100,100,0,0,3,14,0,{cap_an},40,40,0,1
Style: Cap,{a.font},{a.caption_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,-1,0,0,0,100,100,0,0,1,3,2,{cap_an},40,40,0,1
Style: Pop,{a.font},{a.pop_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,5,30,30,0,1
Style: Bar,{a.font},20,{ass_color(a.pop_active).replace('&H', '&H00').rstrip('&')},&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    if a.progress_bar:  # 영상 위 가장자리를 따라 왼쪽에서 오른쪽으로 차오르는 막대
        bar_y = (band[0] - 12) if band else 0
        ev.append(f"Dialogue: 4,0:00:00.00,{ass_time(duration)},Bar,,0,0,0,,"
                  f"{{\\pos(0,{bar_y})\\p1\\fscx0\\t(0,{round(duration * 1000)},\\fscx100)}}"
                  f"m 0 0 l {W} 0 {W} 12 0 12{{\\p0}}")
    if pop_words:
        ev += pop_events(pop_words, duration, a)
        cues = []
    end = ass_time(duration + 1)
    lines = [(a.title1, False), (a.title2, not a.title2_plain)]
    for (text, hl_all), y in zip([l for l in lines if l[0]], ys):
        body = title_markup(text, a.title_color, hl_all)
        ev.append(f"Dialogue: 1,0:00:00.00,{end},Glow,,0,0,0,,{{\\pos({W // 2},{y})\\blur9}}{body}")
        ev.append(f"Dialogue: 2,0:00:00.00,{end},Title,,0,0,0,,{{\\pos({W // 2},{y})}}{body}")
    for c in cues:
        if c["start"] >= duration:
            continue
        text = esc(c["text"])
        stop = min(c["end"], duration)
        t0, t1 = ass_time(c["start"]), ass_time(stop)
        if a.box:  # 박스는 색 구분 없는 한 덩어리로 따로 그린다
            ev.append(f"Dialogue: 0,{t0},{t1},CapBox,,0,0,0,,{{\\pos({W // 2},{cap_y})}}{text}")
        body = caption_body(text, caption_spans(text, a.hl, a.english_color), stop - c["start"], a.typewriter)
        ev.append(f"Dialogue: 3,{t0},{t1},Cap,,0,0,0,,{{\\pos({W // 2},{cap_y})}}{body}")
    return head + "\n".join(ev) + "\n"


# ------------------------------------------------------------------- main
def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", type=Path, help="원본 영상")
    p.add_argument("-o", "--output", type=Path, help="결과 파일 (기본: output/<이름>_reel.mp4)")
    p.add_argument("--title1", default="", help="상단 제목 첫 줄 (흰색). *별표* 로 감싼 부분은 강조색 기울임")
    p.add_argument("--title2", default="", help="상단 제목 둘째 줄 (줄 전체 강조색 기울임. *별표* 를 쓰면 그 부분만)")
    p.add_argument("--title-color", default="yellow", help="제목 강조색 (yellow, red ...)")
    p.add_argument("--title2-plain", action="store_true", help="둘째 줄을 강조하지 않고 흰색으로")
    p.add_argument("--box", action="store_true", help="자막 뒤에 검정 반투명 박스를 깐다 (기준 영상은 박스 없음)")
    p.add_argument("--no-typewriter", dest="typewriter", action="store_false", help="글자가 하나씩 찍히는 효과 끄기")
    p.add_argument("--highlight", action="append", default=[], metavar="단어[:색]",
                   help="자막에서 색을 입힐 단어. 여러 번 지정 가능. 색 기본값 orange")
    p.add_argument("--caption-style", choices=["line", "pop"], default="line",
                   help="line: 한 줄씩(기준 계정 방식). pop: 2~3단어씩 크게, 말하는 단어가 커지며 색이 바뀜(숏폼 방식)")
    p.add_argument("--words", type=Path, help="pop 자막에 쓸 단어별 시각 파일(words.json). --srt 와 함께 다시 만들 때 필요")
    p.add_argument("--pop-size", type=int, default=96)
    p.add_argument("--pop-y", type=int, default=1215, help="pop 자막의 세로 중심 (인스타 화면 하단 UI를 피한 위치)")
    p.add_argument("--pop-active", default="yellow", help="지금 말하는 단어의 색")
    p.add_argument("--progress-bar", action="store_true", help="영상 위쪽에 진행 막대를 그린다")
    p.add_argument("--highlight-color", default="orange", help="색을 따로 적지 않은 강조 단어의 색")
    p.add_argument("--english-color", default="green", help="영어 단어 자동 강조 색 (끄려면 none)")
    p.add_argument("--layout", choices=["auto", "full", "crop", "letterbox", "blur", "square", "43"], default="auto",
                   help="auto: 세로 원본은 full, 가로 원본은 letterbox. crop: 가로 원본 가운데를 세로로 잘라냄")
    p.add_argument("--small-first", action="store_true",
                   help="square·43 배치에서 먼저 잘라 줄인 뒤 무음 컷을 한다 (큰 원본에서 훨씬 빠름)")
    p.add_argument("--no-cut", action="store_true", help="무음 구간을 잘라내지 않음")
    p.add_argument("--min-silence", type=float, default=0.6, help="이 길이(초) 이상의 무음만 제거")
    p.add_argument("--threshold", type=float, default=-35, help="무음 판정 기준 dBFS (조용한 방은 -40~-45)")
    p.add_argument("--srt", type=Path, help="직접 고친 자막 파일. 주면 음성 인식을 건너뜀")
    p.add_argument("--no-captions", action="store_true", help="자막 없이 제목만")
    p.add_argument("--captions-only", action="store_true",
                   help="무음 컷·9:16·받아쓰기까지만 하고 멈춤. 자막을 고친 뒤 --srt 로 이어서 실행")
    p.add_argument("--model", default="large-v3-turbo", help="Whisper 모델")
    p.add_argument("--language", default="ko")
    p.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    p.add_argument("--max-chars", type=int, default=20, help="자막 한 줄 최대 글자 수")
    p.add_argument("--font", default="Pretendard ExtraBold")
    p.add_argument("--title-size", type=int, default=96)
    p.add_argument("--caption-size", type=int, default=62)
    p.add_argument("--title-y", type=int, default=262, help="세로 꽉 찬 화면에서 제목 첫 줄 y (0~1920)")
    p.add_argument("--caption-y", type=int, default=1400, help="세로 꽉 찬 화면에서 자막 아랫변 y")
    p.add_argument("--box-alpha", default="60", help="자막 박스 투명도 00(불투명)~FF(투명)")
    a = p.parse_args()

    src = a.input.resolve()
    if not src.is_file():
        raise SystemExit(f"원본을 찾을 수 없음: {src}")
    a.hl = []
    for h in a.highlight:
        word, _, color = h.partition(":")
        ass_color(color or a.highlight_color)
        a.hl.append((word, color or a.highlight_color))
    if a.english_color.lower() == "none":
        a.english_color = None
    else:
        ass_color(a.english_color)
    ass_color(a.title_color)

    work = ROOT / "work" / src.stem
    work.mkdir(parents=True, exist_ok=True)
    out = (a.output or ROOT / "output" / f"{src.stem}_reel.mp4").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out == src:
        raise SystemExit("결과 파일이 원본과 같습니다.")

    # 1) 원본 측정
    info = run_tool("probe", src, "--json", capture=True)
    v = info["video"]
    sw, sh = v["width"], v["height"]
    if abs(int(v.get("rotation") or 0)) in (90, 270):
        sw, sh = sh, sw
    print(f"원본: {sw}x{sh}, {info['duration']:.1f}초, {v['fps']}fps")
    layout = a.layout
    if layout == "auto":
        layout = "full" if sh > sw else "letterbox"

    # 2) 무음 컷 (자막을 고쳐 다시 돌릴 때는 앞서 만든 9:16 영상을 그대로 쓴다)
    cur = src
    pre_cropped = False
    framed = work / ("02_framed.mp4" if layout == "letterbox" else f"02_framed_{layout}.mp4")
    cut = work / "01_cut.mp4"
    reuse = bool(a.srt) and framed.is_file()
    if reuse:
        print(f"앞서 만든 {framed.name} 재사용 (무음 컷·9:16 생략)")
    elif a.srt and cut.is_file():  # 배치만 바꿔 다시 만들 때: 무음 컷 결과는 그대로 쓴다
        print(f"앞서 만든 {cut.name} 재사용 (무음 컷 생략)")
        cur = cut
        pre_cropped = (work / f"00_small_{layout}.mp4").is_file()  # 이미 잘라 줄인 영상에서 나온 결과다
    else:
        if a.small_first and layout in ("square", "43") and sw > sh:
            # 먼저 가운데를 잘라 1080 폭으로 줄인다. 뒤의 무음 컷·배치가 원본 화질(예: 1440p)로 돌지 않게 된다.
            small = work / f"00_small_{layout}.mp4"
            sm_h = W if layout == "square" else W * 3 // 4
            run_tool("fit", cur, "-o", small, "--aspect", "1:1" if layout == "square" else "4:3", "--fit", "crop",
                     "--width", W, "--height", sm_h, "--fps", 30, "--overwrite")
            cur, pre_cropped = small, True
        if not a.no_cut:
            run_tool("silence", cur, "-o", cut, "--threshold", a.threshold, "--min-silence", a.min_silence,
                     "--timemap", work / "cut_timemap.json", "--overwrite")
            cur = cut

    # 3) 9:16. letterbox: 검은 띠 / blur: 흐린 배경 / square: 가운데를 정사각형으로 잘라 크게 / full·crop: 꽉 채움
    band = None
    if not reuse:
        if layout in ("square", "43") and sw > sh and not pre_cropped:  # 가운데를 1:1 또는 4:3으로 잘라 화면에 더 크게
            cw = sh if layout == "square" else min(sw, sh * 4 // 3 // 2 * 2)
            sq = work / f"01b_{layout}.mp4"
            run_tool("crop", cur, "-o", sq, "--x", (sw - cw) // 2, "--y", 0, "--width", cw, "--height", sh,
                     "--overwrite")
            cur = sq
        fit = {"letterbox": "pad", "square": "pad", "43": "pad", "blur": "blur"}.get(layout, "crop")
        run_tool("fit", cur, "-o", framed, "--aspect", "9:16", "--fit", fit, "--width", W, "--height", H,
                 "--fps", 30, "--overwrite")
    cur = framed
    if layout in ("letterbox", "blur"):
        vid_h = round(W * sh / sw)
        band = ((H - vid_h) // 2, (H + vid_h) // 2)
    elif layout == "square":
        band = ((H - W) // 2, (H + W) // 2)
    elif layout == "43":
        band = ((H - W * 3 // 4) // 2, (H + W * 3 // 4) // 2)
    duration = run_tool("probe", cur, "--json", capture=True)["duration"]

    # 4) 자막
    cues: list[dict] = []
    srt = work / "captions.srt"
    if a.no_captions:
        pass
    elif a.srt:
        cues = read_srt(a.srt.resolve())
        print(f"자막 {len(cues)}줄을 {a.srt} 에서 읽음")
    else:
        prompt = " ".join(x for x in [a.title1, a.title2, *[w for w, _ in a.hl]] if x)
        t0 = time.time()
        words = transcribe(cur, work, a.model, a.language, prompt, a.device)
        TIMINGS.append(("whisper", round(time.time() - t0, 1)))
        (work / "words.json").write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
        cues = words_to_cues(words, a.max_chars, 0.5)
        write_srt(cues, srt)
        print(f"자막 {len(cues)}줄 -> {srt}")

    if a.captions_only:
        save_timings(work, "prep")
        print(f"자막 초안: {srt}")
        print("고친 뒤 같은 명령에서 --captions-only 를 빼고 --srt 로 이 파일을 주면 이어서 만듭니다.")
        return

    # 5) 제목 + 자막 입히기
    ass = work / "overlay.ass"
    pop_words = None
    if a.caption_style == "pop" and not a.no_captions:
        wfile = a.words.resolve() if a.words else work / "words.json"
        if not wfile.is_file():
            raise SystemExit(f"pop 자막에는 단어별 시각 파일이 필요합니다: {wfile}")
        pop_words = json.loads(wfile.read_text(encoding="utf-8"))
    ass.write_text(build_ass(cues, duration, a, band, pop_words), encoding="utf-8-sig")
    titled = work / "03_titled.mp4"
    run_tool("caption", cur, "--ass", ass, "-o", titled, "--overwrite")
    cur = titled

    # 6) 릴스 규격 + 음량 보정
    run_tool("export", cur, "-o", out, "--preset", "reels", "--allow-long", "--normalize", "--overwrite")

    # 7) 검사 + 확인용 시트
    sheet = out.with_name(out.stem + "_sheet.png")
    run_tool("look", out, "--tiles", "3x2", "-o", sheet, "--overwrite")
    try:
        run_tool("check", out, "--platform", "reels")
    except SystemExit as e:
        print(f"규격 검사에서 지적 사항이 있습니다: {e}")

    save_timings(work, "render")
    print(f"\n완료: {out}\n확인용 시트: {sheet}")
    if cues and not a.srt:
        print(f"자막을 고치려면 {srt} 을 수정한 뒤 --srt 로 다시 실행하세요.")


if __name__ == "__main__":
    main()
