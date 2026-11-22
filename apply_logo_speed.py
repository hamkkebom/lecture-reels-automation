#!/usr/bin/env python
"""완성한 그래픽 릴스에 마무리 두 가지를 입힌다.

  1) 아래 검은 띠에 요약 그래픽이 없는 동안 학원 로고를 띄운다 (요약이 뜨면 사라진다)
  2) 전체를 빠르게 한다 (음높이는 그대로)

  .venv\\Scripts\\python apply_logo_speed.py                 # 지시서 전부
  .venv\\Scripts\\python apply_logo_speed.py 그래픽_1부_01_if.json ...   # 일부만
  .venv\\Scripts\\python apply_logo_speed.py --plan          # 로고가 뜨는 구간만 보여 준다

결과: output/<클립>_로고_1.2배.mp4 (+ _sheet.png)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import brand
import make_reel as m
import shortform as sf
import shortform2 as s2

SPEED = 1.2
# 로고 자리·크기는 brand.logo_place (요약 띠 두 줄 자리의 한가운데, 폭 320·높이 130 상자에 맞춤)
MIN_GAP = 2.5  # 이보다 짧은 빈틈에는 로고를 띄우지 않는다 (깜빡이는 것처럼 보인다)


def logo_windows(spec: dict, duration: float) -> list[tuple[float, float]]:
    """아래 띠에 요약 그래픽이 없는 구간들."""
    work = m.ROOT / "work" / spec["clip"]
    words = json.loads((work / "words_fixed.json").read_text(encoding="utf-8"))
    raw = s2.parse_script(spec["script"]) if "script" in spec else spec["chunks"]
    chunks = sf.align(words, [c[:4] for c in raw])
    for c, r in zip(chunks, raw):
        c["zoom"], c["keep"] = int(r[3]), bool(r[4])
    src_dur = m.run_tool("probe", work / "02_framed_43.mp4", "--json", capture=True)["duration"]
    s2.build_pieces(chunks, src_dur)
    by_text = s2.index_chunks(chunks)
    busy = []
    for g in spec.get("lower", []):
        s = by_text[g["at_chunk"]]["new_start"] + 0.1
        e = by_text[g["until_chunk"]]["new_start"] if g.get("until_chunk") else duration
        busy.append((s, e))
    gaps, t = [], 0.0
    for s, e in sorted(busy):
        if s - t >= MIN_GAP:
            gaps.append((t, s - 0.1))
        t = max(t, e)
    if duration - t >= MIN_GAP:
        gaps.append((t, duration))
    return [(round(a, 2), round(b, 2)) for a, b in gaps]


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    specs = [Path(a) for a in args] or sorted(m.ROOT.glob("그래픽_*.json")) + [m.ROOT / "숏폼5_if_will.json"]
    for path in specs:
        t0 = time.time()
        spec = json.loads((m.ROOT / path).read_text(encoding="utf-8"))
        B = brand.load(spec)  # 학원 로고 (지시서의 "academy", 없으면 승리어학원)
        logo = B["logo"]
        if logo and Path(logo).exists():
            logo_w, logo_x, logo_y = brand.logo_place(Path(logo))
        else:
            print(f"[스타일] {B['academy']} 로고가 없어 로고 없이 만듭니다.", flush=True)
            logo = None
        work = m.ROOT / "work" / spec["clip"]
        video = m.ROOT / "output" / f"{spec['clip']}_{spec['tag']}.mp4"
        duration = m.run_tool("probe", video, "--json", capture=True)["duration"]
        gaps = logo_windows(spec, duration) if logo else []
        print(f"{spec['clip']}: 길이 {duration:.1f}초, 로고 구간 {gaps}", flush=True)
        if "--plan" in sys.argv:
            continue
        for i, (a, b) in enumerate(gaps):
            nxt = work / f"05_logo_{i}.mp4"
            cmd = ["overlay", video, "--image", logo, "--position", f"{logo_x},{logo_y}", "--margin", 0,
                   "--scale", logo_w, "--start", a, "--fade", 0.3, "-o", nxt, "--overwrite"]
            if b < duration - 0.05:  # 끝까지 가는 구간은 사라지게 하지 않는다
                cmd += ["--end", b]
            m.run_tool(*cmd)
            video = nxt
        # "out"이 있으면 그 이름으로 (미리보기가 진짜 결과를 덮어쓰지 않게)
        out = m.ROOT / "output" / (f"{spec['out']}.mp4" if spec.get("out") else f"{spec['clip']}_로고_{SPEED}배.mp4")
        m.run_tool("fit", video, "--duration", f"{duration / SPEED:.3f}", "--method", "speed", "-o", out, "--overwrite")
        m.run_tool("look", out, "--tiles", "4x2", "--width", "1600", "-o", out.with_name(out.stem + "_sheet.png"),
                   "--overwrite")
        print(f"=== {spec['clip']}: {duration:.1f}초 -> {duration / SPEED:.1f}초, 걸린 시간 {time.time() - t0:.0f}초",
              flush=True)


if __name__ == "__main__":
    main()
