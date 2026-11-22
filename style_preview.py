#!/usr/bin/env python
"""스타일 틀 미리보기: 같은 클립을 틀마다 만들어 한 장의 비교 이미지로 모은다.

  .venv\\Scripts\\python style_preview.py 그래픽_1부_01_if.json            # 승리어학원 + 샘플학원(틀 3개)
  .venv\\Scripts\\python style_preview.py 그래픽_1부_01_if.json --academy 가나학원   # 등록한 학원 하나

결과: output/스타일미리보기/<클립>_<틀>.mp4, 비교 이미지 output/스타일미리보기/<클립>_비교.png
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "스타일미리보기"
WORK = ROOT / "work" / "스타일미리보기"
PY = sys.executable

# 샘플학원: 승리어학원과 다른 색 + 정사각형 로고로 틀을 비교한다
SAMPLE_COLORS = {"accent": "35C7FF", "english": "FFD84D", "point": "FF6FA8"}


def sample_logo() -> Path:
    from PIL import Image, ImageDraw, ImageFont
    p = WORK / "샘플로고.png"
    if p.exists():
        return p
    WORK.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((10, 10, 390, 390), fill=(53, 199, 255, 255))
    try:
        f = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 120)
    except OSError:
        f = ImageFont.load_default()
    d.text((200, 200), "샘플", font=f, fill="white", anchor="mm")
    im.save(p)
    return p


def run(spec: dict, name: str) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    clip = spec["clip"]
    s = dict(spec, tag=f"미리보기_{name}", out=f"스타일미리보기/{clip}_{name}")
    f = WORK / f"{clip}_{name}.json"
    f.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    for script in ("shortform2.py", "apply_logo_speed.py"):
        r = subprocess.run([PY, str(ROOT / script), str(f)], cwd=ROOT)
        if r.returncode:
            raise SystemExit(f"{script} 실패: {name}")
    tmp = ROOT / "output" / f"{clip}_미리보기_{name}.mp4"  # shortform2 중간 결과는 지운다
    for x in (tmp, tmp.with_name(tmp.stem + "_sheet.png")):
        x.unlink(missing_ok=True)
    return OUT / f"{clip}_{name}.mp4"


def card_times(clip: str) -> list[float]:
    """그래픽 카드 화면이 한창 보이는 시각들 (1.2배 빠르게 한 뒤 기준). overlay_h.ass 의 바탕판(층 5)에서 읽는다."""
    import re
    import apply_logo_speed as al
    ass = (ROOT / "work" / clip / "overlay_h.ass").read_text(encoding="utf-8-sig")
    out = []
    for mt in re.finditer(r"^Dialogue: 5,(\d+):(\d+):([\d.]+),(\d+):(\d+):([\d.]+),Bar,.*\\1c[^\\]*\\fad\(120,110\)", ass, re.M):
        h1, m1, s1, h2, m2, s2 = mt.groups()
        a = int(h1) * 3600 + int(m1) * 60 + float(s1)
        b = int(h2) * 3600 + int(m2) * 60 + float(s2)
        out.append((a + (b - a) * 0.75) / al.SPEED)  # 카드 위 글자가 다 나온 뒤쯤
    return out


def compare(videos: list[tuple[str, Path]], out: Path, times: list[float]) -> None:
    from PIL import Image, ImageDraw, ImageFont
    sys.path.insert(0, str(ROOT))
    import make_reel as m
    rows = []
    for name, v in videos:
        frames = []
        for t in times:
            png = WORK / f"{v.stem}_{t:.1f}.png"
            m.run_tool("look", v, "--at", f"{t:.2f}", "--width", "360", "-o", png, "--overwrite")
            frames.append(Image.open(png).convert("RGB"))
        rows.append((name, frames))
    fw, fh = rows[0][1][0].size
    label_w = 190
    sheet = Image.new("RGB", (label_w + fw * len(times), fh * len(rows)), "white")
    d = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 26)
    for r, (name, frames) in enumerate(rows):
        d.multiline_text((14, r * fh + fh // 2 - 30), name.replace(" ", "\n", 1), font=font, fill="black")
        for c, im in enumerate(frames):
            sheet.paste(im, (label_w + c * fw, r * fh))
    sheet.save(out)


def main() -> None:
    spec_path = Path(sys.argv[1])
    spec = json.loads((ROOT / spec_path).read_text(encoding="utf-8"))
    if "--academy" in sys.argv:
        acad = sys.argv[sys.argv.index("--academy") + 1]
        variants = [(acad, dict(spec, academy=acad))]
    else:
        logo = str(sample_logo())
        variants = [("승리어학원 기본", dict(spec))]
        for tpl, label in (("black", "샘플 블랙"), ("chalk", "샘플 칠판"), ("brand", "샘플 학원색")):
            variants.append((label, dict(spec, academy="샘플학원",
                                         brand={"template": tpl, "colors": SAMPLE_COLORS, "logo": logo})))
    made = [(label, run(s, label.replace(" ", "_"))) for label, s in variants]
    sys.path.insert(0, str(ROOT))
    import make_reel as m
    dur = m.run_tool("probe", made[0][1], "--json", capture=True)["duration"]
    times = [dur * 0.06] + card_times(spec["clip"])[:3] + [dur * 0.62, dur * 0.97]
    out = OUT / f"{spec['clip']}_비교.png"
    compare(made, out, times)
    print(f"비교 이미지: {out}")


if __name__ == "__main__":
    main()
