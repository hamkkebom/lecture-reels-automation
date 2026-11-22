#!/usr/bin/env python
"""릴스_설정.json 의 구간들을 한꺼번에 처리한다.

  .venv\\Scripts\\python batch_reels.py prep      # 구간 자르기 + 무음 컷 + 9:16 + 자막 초안
  .venv\\Scripts\\python batch_reels.py render    # (자막 교정 후) 제목·자막 입히고 릴스로 내보내기
  .venv\\Scripts\\python batch_reels.py render 1부_01_if   # 특정 구간만

구간의 정확한 시작·끝은 work/clips/<rough>/rough_words.json (단어별 시각)에서
start_word / end_word 로 찾는다. 단계별 시간은 work/batch_timing.json 에 쌓인다.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import make_reel as m

ROOT = m.ROOT
CFG = json.loads((ROOT / "릴스_설정.json").read_text(encoding="utf-8"))
LOG = ROOT / "work" / "batch_timing.json"


def bounds(c: dict) -> tuple[float, float]:
    rough = ROOT / "work" / "clips" / c.get("rough", "-") / "rough_words.json"
    whole = not rough.is_file()
    if whole:  # 전체 받아쓰기에 단어별 시각이 있으면 구간마다 다시 받아쓸 필요가 없다
        rough = ROOT / "work" / Path(c["src"]).stem / "transcript_words.json"
    words = json.loads(rough.read_text(encoding="utf-8"))
    start = next(w for w in words if w["start"] >= c["start_after"] and w["text"].startswith(c["start_word"]))
    end = next(w for w in words
               if w["start"] >= c.get("end_after", start["start"]) and w["text"].startswith(c["end_word"]))
    s, e = start["start"] - 0.25, end["end"] + 0.35
    if whole:
        # 전체 받아쓰기는 짧게 끊어 말한 단어를 빠뜨릴 때가 있다(예: "띵, 원," 누락).
        # 앞말이 끝난 직후부터, 뒷말이 시작되기 직전까지로 넓혀 잡는다. 늘어난 무음은 뒤의 무음 컷이 걷어 낸다.
        i, j = words.index(start), words.index(end)
        if i:
            s = max(s - 8.0, min(s, words[i - 1]["end"] + 0.2))
        if j + 1 < len(words):
            e = min(e + 8.0, max(e, words[j + 1]["start"] - 0.2))
    return round(s, 2), round(e, 2)


def apply_fix(words: list[dict], old: str, new: str) -> bool:
    """단어 목록에서 old(띄어쓰기로 나눈 연속 단어)를 처음 한 번 찾아 new로 바꾼다. 시각은 구간 안에서 고르게 나눈다."""
    def norm(t: str) -> str:
        return t.strip(".,")

    want = [norm(t) for t in old.split()]
    n = len(want)
    for i in range(len(words) - n + 1):
        if [norm(w["text"]) for w in words[i:i + n]] == want:
            start, end = words[i]["start"], words[i + n - 1]["end"]
            tail = words[i + n - 1]["text"][len(words[i + n - 1]["text"].rstrip(".,")):]  # 원래 끝 문장부호 유지
            parts = new.split()
            step = (end - start) / max(len(parts), 1)
            repl = [{"start": start + k * step, "end": start + (k + 1) * step, "text": p} for k, p in enumerate(parts)]
            if repl and tail and not repl[-1]["text"].endswith(tuple(".,?!")):
                repl[-1]["text"] += tail
            words[i:i + n] = repl
            return True
    return False


def reel_args(c: dict) -> list[str]:
    args = ["--title1", c["title1"]]
    if c.get("title2"):
        args += ["--title2", c["title2"]]
    if c.get("title2_plain"):
        args.append("--title2-plain")
    if c.get("title_color"):
        args += ["--title-color", c["title_color"]]
    for h in c.get("highlight", []):
        args += ["--highlight", h]
    st = c.get("style", {})  # 시안별 편집 스타일
    for key, flag in [("layout", "--layout"), ("title_color", "--title-color"), ("english_color", "--english-color"),
                      ("highlight_color", "--highlight-color"), ("caption_size", "--caption-size"),
                      ("title_size", "--title-size"), ("box_alpha", "--box-alpha")]:
        if key in st:
            args += [flag, str(st[key])]
    for key, flag in [("caption_style", "--caption-style"), ("pop_size", "--pop-size"), ("pop_y", "--pop-y"),
                      ("pop_active", "--pop-active")]:
        if key in st:
            args += [flag, str(st[key])]
    if st.get("progress_bar"):
        args.append("--progress-bar")
    wf = ROOT / "work" / c["name"] / "words_fixed.json"
    if st.get("caption_style") == "pop" and wf.is_file():
        args += ["--words", str(wf)]
    if st.get("box"):
        args.append("--box")
    if st.get("typewriter") is False:
        args.append("--no-typewriter")
    return args


def record(entry: dict) -> None:
    data = json.loads(LOG.read_text(encoding="utf-8")) if LOG.is_file() else []
    data.append(entry)
    LOG.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    only = set(sys.argv[2:])
    if stage == "cues":  # 받아쓰기는 다시 하지 않고, 저장된 단어 시각으로 자막 줄만 다시 나눈다
        for c in CFG["clips"]:
            if only and c["name"] not in only:
                continue
            work = ROOT / "work" / c["name"]
            words = json.loads((work / "words.json").read_text(encoding="utf-8"))
            missed = []
            for old, new in c.get("fix", []):
                if not apply_fix(words, old, new):
                    missed.append(old)
            (work / "words_fixed.json").write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
            cues = m.words_to_cues(words, 20, 0.5)
            out = work / ("captions_fixed.srt" if c.get("fix") else "captions.srt")
            m.write_srt(cues, out)
            print(f"{c['name']}: 자막 {len(cues)}줄 -> {out.name}" + (f" / 못 찾은 교정: {missed}" if missed else ""))
        return
    if stage not in ("prep", "render"):
        raise SystemExit(__doc__)
    clips_dir = ROOT / "클립"
    clips_dir.mkdir(exist_ok=True)
    env = m.tool_env()
    for c in CFG["clips"]:
        if only and c["name"] not in only:
            continue
        clip = clips_dir / f"{c['name']}.mp4"
        work = ROOT / "work" / c["name"]
        t0 = time.time()
        entry = {"clip": c["name"], "stage": stage, "at": time.strftime("%H:%M:%S")}
        if stage == "prep":
            s, e = bounds(c)
            entry["source_range"] = [s, e]
            entry["source_seconds"] = round(e - s, 1)
            m.TIMINGS.clear()
            m.run_tool("cut", ROOT / c["src"], "--start", s, "--end", e, "--smart", "-o", clip, "--overwrite")
            entry["cut"] = m.TIMINGS[-1][1]
            cmd = [sys.executable, str(ROOT / "make_reel.py"), str(clip), "--captions-only", "--small-first",
                   *reel_args(c)]
        else:
            srt = work / "captions_fixed.srt"
            if not srt.is_file():
                srt = work / "captions.srt"
            entry["srt"] = srt.name
            cmd = [sys.executable, str(ROOT / "make_reel.py"), str(clip), "--srt", str(srt), *reel_args(c)]
            tag = c.get("style", {}).get("tag")
            if tag:  # 시안 이름을 파일명에 붙여 앞서 만든 결과를 덮어쓰지 않는다
                entry["style"] = tag
                cmd += ["-o", str(ROOT / "output" / f"{c['name']}_{tag}.mp4")]
        proc = subprocess.run(cmd, env=env)
        entry["ok"] = proc.returncode == 0
        entry["total"] = round(time.time() - t0, 1)
        tfile = work / f"timing_{stage}.json"
        if tfile.is_file():
            entry["steps"] = json.loads(tfile.read_text(encoding="utf-8"))
        record(entry)
        print(f"=== {c['name']} {stage}: {entry['total']}초 ({'성공' if entry['ok'] else '실패'})", flush=True)


if __name__ == "__main__":
    main()
