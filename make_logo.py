#!/usr/bin/env python
"""로고 그림(투명 바탕 PNG)에서 빈 여백을 잘라 영상에 올릴 크기로 만든다.

  .venv\\Scripts\\python make_logo.py 원본로고.png

결과: 로고/로고_투명.png, 로고/미리보기_검정.png (검은 화면 위에서 어떻게 보이는지)
"""
from __future__ import annotations

import sys

from PIL import Image

import make_reel as m


def main() -> None:
    src = Image.open(sys.argv[1]).convert("RGBA")
    x0, y0, x1, y1 = src.getchannel("A").getbbox()
    out = src.crop((x0 - 8, y0 - 8, x1 + 8, y1 + 8))
    # 마크 안의 V 는 원래 흰색인데 그림에서는 뚫려 있어 검은 화면에서 구멍처럼 보인다. 흰색으로 채운다.
    a = out.getchannel("A").load()
    w, h = out.size
    cols = [any(a[x, y] > 40 for y in range(h)) for x in range(w)]
    first = cols.index(True)
    mark_end = first + cols[first:].index(False)  # 마크와 글자 사이 빈 칸
    px = out.load()
    for y in range(h):
        row = [x for x in range(first, mark_end) if a[x, y] > 128]
        if not row:
            continue
        for x in range(row[0], row[-1] + 1):
            r, g, b, al = px[x, y]
            k = al / 255  # 빨강을 흰색 위에 얹은 색
            px[x, y] = (round(r * k + 255 * (1 - k)), round(g * k + 255 * (1 - k)), round(b * k + 255 * (1 - k)), 255)
    dst = m.ROOT / "로고"
    dst.mkdir(exist_ok=True)
    out.save(dst / "로고_투명.png")
    black = Image.new("RGB", out.size, (0, 0, 0))
    black.paste(out, (0, 0), out)
    black.save(dst / "미리보기_검정.png")
    print(f"완료: {dst / '로고_투명.png'} {out.size}")


if __name__ == "__main__":
    main()
