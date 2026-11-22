#!/usr/bin/env python
"""숏폼형 편집: 사람이 정한 자막 끊는 자리 + 종류별 색·동작 + 화면 확대 컷 + 요약 카드.

  .venv\\Scripts\\python shortform.py 숏폼_if_will.json

준비물: batch_reels.py prep / cues 로 만든 work/<clip>/02_framed_43.mp4 와 words_fixed.json.
지시서(JSON)의 chunks 문구는 words_fixed.json 의 단어 순서와 정확히 같아야 한다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import make_reel as m

W, H = m.W, m.H
SIZE = {"n": 92, "q": 112, "k": 108, "t": 100, "a": 66}
m.COLORS.setdefault("gray", "CFCFCF")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def align(words: list[dict], chunks: list[list]) -> list[dict]:
    """chunks 문구를 단어 목록에 차례로 맞춰 시작·끝 시각을 붙인다. 어긋나면 어디서 틀렸는지 알려 준다."""
    out, i = [], 0
    for text, kind, color, zoom in chunks:
        n = len(text.split())
        got = " ".join(w["text"] for w in words[i:i + n])
        if norm(got) != norm(text):
            raise SystemExit(f"자막 문구가 단어 목록과 다릅니다.\n  지시서: {text}\n  단어들: {got}")
        out.append({"text": text, "kind": kind, "color": color or "white", "zoom": bool(zoom),
                    "words": words[i:i + n], "start": words[i]["start"], "end": words[i + n - 1]["end"]})
        i += n
    if i != len(words):
        raise SystemExit(f"지시서가 단어 {len(words) - i}개를 남겼습니다: {' '.join(w['text'] for w in words[i:])}")
    return out


def zoom_ranges(chunks: list[dict], duration: float) -> list[tuple[float, float, bool]]:
    """연속된 같은 확대 상태를 한 구간으로 묶는다. 경계는 프레임(1/30초)에 맞춘다."""
    marks = [(0.0, chunks[0]["zoom"])]
    for c in chunks[1:]:
        if c["zoom"] != marks[-1][1]:
            marks.append((max(0.0, round((c["start"] - 0.08) * 30) / 30), c["zoom"]))
    out = []
    for k, (t, z) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else duration
        if end - t > 0.2:
            out.append((t, end, z))
    return out


def make_zoomed(src: Path, work: Path, ranges: list[tuple[float, float, bool]], factor: float) -> Path:
    """확대 구간만 가운데를 잘라 다시 키운 뒤 전체를 이어 붙인다."""
    cw = int(W / factor) // 2 * 2
    chh = int(H / factor) // 2 * 2
    parts = []
    for k, (a, b, z) in enumerate(ranges):
        piece = work / f"z_{k:02d}.mp4"
        m.run_tool("cut", src, "--start", f"{a:.3f}", "--end", f"{b:.3f}", "--codec", "h264", "-o", piece, "--overwrite")
        if z:
            crop = work / f"z_{k:02d}_crop.mp4"
            m.run_tool("crop", piece, "-o", crop, "--x", (W - cw) // 2, "--y", (H - chh) // 2,
                       "--width", cw, "--height", chh, "--overwrite")
            big = work / f"z_{k:02d}_big.mp4"
            m.run_tool("fit", crop, "-o", big, "--width", W, "--height", H, "--aspect", "9:16", "--fit", "crop",
                       "--fps", 30, "--overwrite")
            piece = big
        parts.append(piece)
    out = work / "02z_zoomed.mp4"
    m.run_tool("join", *parts, "--transition", "none", "--width", W, "--height", H, "--fps", 30,
               "-o", out, "--overwrite")
    return out


def chunk_event(c: dict, end: float, y: int) -> str:
    kind, size = c["kind"], SIZE[c["kind"]]
    color = m.ass_color(c["color"])
    dur = max(1, round((end - c["start"]) * 1000))
    head = f"\\pos({W // 2},{y})\\fs{size}"
    if kind == "n":  # 보통: 흰 글씨, 말하는 단어만 노랗게 커짐
        parts = []
        for j, w in enumerate(c["words"]):
            on = round((w["start"] - c["start"]) * 1000)
            off = round(((c["words"][j + 1]["start"] if j + 1 < len(c["words"]) else end) - c["start"]) * 1000)
            text = m.esc(re.sub(r"[.,]+$", "", w["text"]))
            parts.append(f"{{\\1c&HFFFFFF&\\fscx100\\fscy100\\t({on},{on + 70},\\1c{m.ass_color('yellow')}\\fscx112\\fscy112)"
                         f"\\t({off},{off + 70},\\1c&HFFFFFF&\\fscx100\\fscy100)}}{text}")
        return f"{{{head}\\fad(50,0)}}" + " ".join(parts)
    text = m.esc(re.sub(r"[.,]+$", "", c["text"]))
    if kind == "a":  # 곁말: 작게, 기울여서, 아래에서 살짝 올라옴
        return f"{{\\move({W // 2},{y + 40},{W // 2},{y},0,160)\\fs{size}\\i1\\1c{color}\\fad(80,80)}}{text}"
    if kind == "t":  # 용어: 색 글씨가 옆에서 밀려 들어옴
        return f"{{\\move({W // 2 - 120},{y},{W // 2},{y},0,140)\\fs{size}\\1c{color}\\fad(60,0)}}{text}"
    # q 질문·k 핵심: 작게 시작해 넘치게 커졌다가 제자리로 (튀어나오는 느낌)
    pop = "\\fscx55\\fscy55\\t(0,110,\\fscx122\\fscy122)\\t(110,200,\\fscx100\\fscy100)"
    extra = ""
    if kind == "q":  # 질문은 좌우로 한 번 흔들림
        extra = "\\frz-5\\t(0,110,\\frz4)\\t(110,220,\\frz0)"
    if c["color"] == "red":  # 금지·경고는 굵은 흰 테두리 + 떨림
        extra += "\\3c&HFFFFFF&\\bord9\\t(200,260,\\frz-3)\\t(260,320,\\frz3)\\t(320,380,\\frz0)"
    return f"{{{head}\\1c{color}{pop}{extra}}}{text}"


def main() -> None:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    work = m.ROOT / "work" / spec["clip"]
    framed = work / "02_framed_43.mp4"
    words = json.loads((work / "words_fixed.json").read_text(encoding="utf-8"))
    chunks = align(words, spec["chunks"])
    t0 = time.time()

    duration = m.run_tool("probe", framed, "--json", capture=True)["duration"]
    ranges = zoom_ranges(chunks, duration)
    print("확대 구간:", [(round(a, 2), round(b, 2)) for a, b, z in ranges if z])
    video = work / "02z_zoomed.mp4"
    if video.is_file() and "--rezoom" not in sys.argv:
        print(f"앞서 만든 {video.name} 재사용 (확대 구간을 바꿨으면 --rezoom 을 붙여 다시 실행)")
    else:
        video = make_zoomed(framed, work, ranges, spec.get("zoom", 1.15))
    duration = m.run_tool("probe", video, "--json", capture=True)["duration"]

    band = ((H - W * 3 // 4) // 2, (H + W * 3 // 4) // 2)
    a = argparse.Namespace(
        title1=spec["title1"], title2=spec.get("title2", ""), title2_plain=False, title_color="yellow",
        title_size=96, title_y=262, caption_y=1400, caption_size=62, font="Pretendard ExtraBold", box_alpha="60",
        box=False, typewriter=False, hl=[], english_color=None, pop_size=92, pop_y=1215, pop_active="yellow",
        progress_bar=True)
    ass = m.build_ass([], duration, a, band, None).rstrip("\n").split("\n")

    ev = []
    for k, c in enumerate(chunks):
        nxt = chunks[k + 1]["start"] if k + 1 < len(chunks) else duration
        end = min(max(c["end"] + 0.25, c["start"] + 0.5), nxt - 0.01, duration)
        if end > c["start"]:
            ev.append(f"Dialogue: 3,{m.ass_time(c['start'])},{m.ass_time(end)},Pop,,0,0,0,,{chunk_event(c, end, a.pop_y)}")
    for card in spec.get("cards", []):  # 요약 카드: 해당 문구가 나올 때 아래 띠에 올라와 끝까지 남는다
        c = next(x for x in chunks if x["text"] == card["from_chunk"])
        col = m.ass_color(card["color"])
        ev.append(f"Dialogue: 2,{m.ass_time(c['start'] + 0.3)},{m.ass_time(duration)},Card,,0,0,0,,"
                  f"{{\\move({W // 2},{card['y'] + 60},{W // 2},{card['y']},0,220)\\fad(150,0)"
                  f"\\3c{col}}}{m.esc(card['text'])}")
    # 카드용 스타일(색 상자 위 흰 글씨)을 [Events] 앞에 끼워 넣는다
    at = ass.index("[Events]")
    ass.insert(at - 1, "Style: Card,Pretendard ExtraBold,48,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
                       "-1,0,0,0,100,100,0,0,3,14,0,5,30,30,0,1")
    ass_file = work / "overlay_shortform.ass"
    ass_file.write_text("\n".join(ass + ev) + "\n", encoding="utf-8-sig")

    titled = work / "03_titled_shortform.mp4"
    m.run_tool("caption", video, "--ass", ass_file, "-o", titled, "--overwrite")
    out = m.ROOT / "output" / f"{spec['clip']}_{spec['tag']}.mp4"
    m.run_tool("export", titled, "-o", out, "--preset", "reels", "--allow-long", "--normalize", "--overwrite")
    m.run_tool("look", out, "--tiles", "3x2", "-o", out.with_name(out.stem + "_sheet.png"), "--overwrite")
    try:
        m.run_tool("check", out, "--platform", "reels")
    except SystemExit as e:
        print(f"규격 검사 지적: {e}")
    m.save_timings(work, "shortform")
    print(f"완료: {out} ({time.time() - t0:.0f}초)")


if __name__ == "__main__":
    main()
