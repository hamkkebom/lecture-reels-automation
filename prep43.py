#!/usr/bin/env python
"""shortform2.py 준비물 만들기: 01_cut.mp4 -> 02_framed_43.mp4 + 강사 위치를 훑어볼 시트.

  .venv\\Scripts\\python prep43.py 1부_01_if 1부_05_fact ...

시트(band_sheet.png)는 약 2초 간격 그림이다. 강사가 화면 밖에 있는 구간을 찾는 데 쓴다.
"""
from __future__ import annotations

import math
import sys
import time

import make_reel as m

W, H = m.W, m.H
TOP = (H - W * 3 // 4) // 2


def main() -> None:
    for name in sys.argv[1:]:
        t0 = time.time()
        work = m.ROOT / "work" / name
        cut = work / "01_cut.mp4"
        info = m.run_tool("probe", cut, "--json", capture=True)
        sw, sh = info["video"]["width"], info["video"]["height"]
        cw = min(sw, sh * 4 // 3 // 2 * 2)
        sq, framed = work / "01b_43.mp4", work / "02_framed_43.mp4"
        if not framed.is_file():
            m.run_tool("crop", cut, "-o", sq, "--x", (sw - cw) // 2, "--y", 0, "--width", cw, "--height", sh,
                       "--overwrite")
            m.run_tool("fit", sq, "-o", framed, "--aspect", "9:16", "--fit", "pad", "--width", W, "--height", H,
                       "--fps", 30, "--overwrite")
        band = work / "band_only.mp4"
        m.run_tool("crop", framed, "-o", band, "--x", 0, "--y", TOP, "--width", W, "--height", W * 3 // 4,
                   "--overwrite")
        rows = math.ceil(info["duration"] / 2 / 8)
        m.run_tool("look", band, "--tiles", f"8x{rows}", "--width", "2400", "-o", work / "band_sheet.png",
                   "--overwrite")
        print(f"=== {name}: {info['duration']:.1f}초, 시트 8x{rows}, 걸린 시간 {time.time() - t0:.0f}초", flush=True)


if __name__ == "__main__":
    main()
