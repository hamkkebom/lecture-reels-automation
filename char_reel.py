#!/usr/bin/env python
"""세로로 꽉 찬 캐릭터 영상(Seedance 생성물)에 제목·자막·규칙 표시를 입힌다.

  .venv\\Scripts\\python char_reel.py 캐릭터_if_will.json

준비물: make_reel.py --no-cut --layout full --captions-only 로 만든
work/<clip>/02_framed_full.mp4 와 words.json.
지시서의 chunks 문구는 (fix 를 적용한 뒤의) 단어 순서와 정확히 같아야 한다.
얼굴을 가리지 않도록 제목과 규칙 표시는 맨 위(머리카락 높이), 자막은 가슴 높이에 둔다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import batch_reels as br
import make_reel as m
import shortform as sf

W, H = m.W, m.H


def main() -> None:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    work = m.ROOT / "work" / spec["clip"]
    video = work / spec.get("video", "02_framed_full.mp4")
    words = json.loads((work / spec.get("words", "words.json")).read_text(encoding="utf-8"))
    for old, new in spec.get("fix", []):
        if not br.apply_fix(words, old, new):
            raise SystemExit(f"교정할 문구를 찾지 못했습니다: {old}")
    chunks = sf.align(words, spec["chunks"])
    duration = m.run_tool("probe", video, "--json", capture=True)["duration"]
    t0 = time.time()

    a = argparse.Namespace(
        title1=spec["title1"], title2=spec.get("title2", ""), title2_plain=False, title_color="yellow",
        title_size=spec.get("title_size", 92), title_y=spec.get("title_y", 150), caption_y=1400, caption_size=62,
        font="Pretendard ExtraBold", box_alpha="60", box=False, typewriter=False, hl=[], english_color=None,
        pop_size=92, pop_y=spec.get("caption_y", 1420), pop_active="yellow", progress_bar=False)
    ass = m.build_ass([], duration, a, None, None).rstrip("\n").split("\n")
    at = ass.index("[Events]")
    ass.insert(at - 1, "Style: Card,Pretendard ExtraBold,54,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
                       "-1,0,0,0,100,100,0,0,3,16,0,5,30,30,0,1")
    ev = []
    for k, c in enumerate(chunks):
        nxt = chunks[k + 1]["start"] if k + 1 < len(chunks) else duration
        end = min(max(c["end"] + 0.3, c["start"] + 0.55), nxt - 0.01, duration)
        if end > c["start"]:
            ev.append(f"Dialogue: 3,{m.ass_time(c['start'])},{m.ass_time(end)},Pop,,0,0,0,,"
                      f"{sf.chunk_event(c, end, a.pop_y)}")

    # 규칙 표시: 제목 바로 아래에 한 번에 하나씩, 다음 표시가 나올 때까지 남는다
    by_text = {c["text"]: c for c in chunks}
    chips = spec.get("chips", [])
    cy = spec.get("chip_y", 335)
    for i, ch in enumerate(chips):
        s = by_text[ch["at_chunk"]]["start"] + 0.05
        e = by_text[chips[i + 1]["at_chunk"]]["start"] + 0.05 if i + 1 < len(chips) else duration
        ink = "&H000000&" if ch["color"] in ("yellow", "mint") else "&HFFFFFF&"
        ev.append(f"Dialogue: 2,{m.ass_time(s)},{m.ass_time(e)},Card,,0,0,0,,"
                  f"{{\\move({W // 2},{cy - 40},{W // 2},{cy},0,180)\\fad(110,90)\\1c{ink}"
                  f"\\3c{m.ass_color(ch['color'])}}}{m.esc(ch['text'])}")

    ass_file = work / "overlay_char.ass"
    ass_file.write_text("\n".join(ass + ev) + "\n", encoding="utf-8-sig")
    titled = work / "03_titled_char.mp4"
    m.run_tool("caption", video, "--ass", ass_file, "-o", titled, "--overwrite")
    out = m.ROOT / "output" / f"{spec['out']}.mp4"
    m.run_tool("export", titled, "-o", out, "--preset", "reels", "--allow-long", "--normalize", "--overwrite")
    m.run_tool("look", out, "--tiles", "6x2", "--width", "1800", "-o", out.with_name(out.stem + "_sheet.png"),
               "--overwrite")
    try:
        m.run_tool("check", out, "--platform", "reels")
    except SystemExit as e:
        print(f"규격 검사 지적: {e}")
    print(f"완료: {out} / {duration:.1f}초 / 걸린 시간 {time.time() - t0:.0f}초")


if __name__ == "__main__":
    main()
