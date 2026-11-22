"""학원별 스타일(틀·색·로고)을 편집 프로그램에 입힌다.

학원 설정은 관리자 페이지(제출 사이트)에서 정하고, 여기서 받아 와 `로고/학원/`에 저장해 둔다
(인터넷이 끊겨도 마지막으로 받은 설정으로 작업한다).

지시서(그래픽_*.json)에 "academy": "학원 이름" 을 적으면 그 학원 스타일로 만든다. 없으면 승리어학원.
미리보기·시험용으로 "brand": {"template": "black", "colors": {...}} 를 직접 적을 수도 있다.

색은 이름으로 바꿔 끼운다. 지시서와 그래픽 코드가 쓰는 색 이름의 뜻:
  yellow = 제목·강조색(accent)   green = 영어 단어색(english)   orange = 포인트색(point)
  navy/card/slate/dim = 틀의 바탕색   mint·red 는 모든 학원 공통 (결과·경고)
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "로고" / "학원"
DEFAULT_ACADEMY = "승리어학원"

# 스타일 틀. 모두 어두운 바탕 + 흰 글자라서 학원 색만 바꿔도 읽기 쉽다.
# 이 목록과 제출사이트/src/index.js 의 TEMPLATES 는 id·이름을 맞춰 둔다.
TEMPLATES: dict[str, dict] = {
    "h4": {"name": "기본 (남색 카드)", "font": "Pretendard ExtraBold",
           "navy": "0C1424", "card": "17243C", "slate": "24324F", "dim": "6F82A6", "panel": "0C121E", "end": "080C14"},
    "black": {"name": "블랙 (진한 글씨)", "font": "Pretendard Black",
              "navy": "0A0A0B", "card": "1C1C1F", "slate": "2C2C31", "dim": "8A8A93", "panel": "0A0A0B", "end": "050505"},
    "chalk": {"name": "칠판 (초록 바탕)", "font": "NanumGothic ExtraBold",
              "navy": "102219", "card": "1B3528", "slate": "284A39", "dim": "7FA591", "panel": "0F1F17", "end": "0A150F"},
    "brand": {"name": "학원색 바탕", "font": "Pretendard ExtraBold", "derive": True},
}
DEFAULT_COLORS = {"accent": "FFD400", "english": "3DDC5A", "point": "FF8A1F"}

# 로고가 들어갈 상자 (아래 요약 띠 자리의 한가운데). 승리어학원 로고(가로로 긴 모양)는 폭 320에 맞는다.
LOGO_BOX_W, LOGO_BOX_H, LOGO_CX, LOGO_CY = 320, 130, 540, 1573.5


# ---------------------------------------------------------------- 색 계산
def _rgb(h: str) -> tuple[int, int, int]:
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(c: tuple[float, float, float]) -> str:
    return "".join(f"{max(0, min(255, round(v))):02X}" for v in c)


def luminance(h: str) -> float:
    def ch(v: int) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def mix(h: str, other: str, t: float) -> str:
    a, b = _rgb(h), _rgb(other)
    return _hex(tuple(x + (y - x) * t for x, y in zip(a, b)))


def readable_on_dark(h: str, bg: str, need: float = 4.5) -> str:
    """어두운 바탕 위에서 글자로 읽히도록, 너무 어두운 색은 흰색 쪽으로 밝힌다 (명암비 need 이상)."""
    def contrast(x: str) -> float:
        l1, l2 = luminance(x), luminance(bg)
        return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)
    t, out = 0.0, h
    while contrast(out) < need and t < 1:
        t += 0.05
        out = mix(h, "FFFFFF", t)
    return out


# ---------------------------------------------------------------- 설정 받기
def _fetch_academies() -> list[dict] | None:
    try:
        cfg = json.loads((ROOT / "제출받기_설정.json").read_text(encoding="utf-8-sig"))
        req = urllib.request.Request(cfg["url"].rstrip("/") + "/api/admin/academies",
                                     headers={"authorization": "Bearer " + cfg["token"], "user-agent": "Mozilla/5.0 (submit-fetcher)"})
        with urllib.request.urlopen(req, timeout=20) as r:
            acads = json.load(r)["academies"]
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / "학원목록.json").write_text(json.dumps(acads, ensure_ascii=False, indent=1), encoding="utf-8")
        for a in acads:
            if a.get("hasLogo"):
                _fetch_logo(cfg, a)
        return acads
    except Exception as e:
        print(f"[스타일] 학원 설정을 받아 오지 못했습니다({e}). 저장해 둔 설정을 씁니다.", flush=True)
        f = CACHE / "학원목록.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def _fetch_logo(cfg: dict, a: dict) -> None:
    raw = CACHE / f"{a['id']}_원본.png"
    out = CACHE / f"{a['id']}_로고.png"
    stamp = CACHE / f"{a['id']}_로고.stamp"
    if out.exists() and stamp.exists() and stamp.read_text() == a.get("updated", ""):
        return
    req = urllib.request.Request(cfg["url"].rstrip("/") + f"/api/admin/academy/logo?id={a['id']}",
                                 headers={"authorization": "Bearer " + cfg["token"], "user-agent": "Mozilla/5.0 (submit-fetcher)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw.write_bytes(r.read())
    trim_logo(raw, out)
    stamp.write_text(a.get("updated", ""))


def trim_logo(src: Path, out: Path, pad: int = 8) -> None:
    """투명한 테두리를 잘라 내고 8px 여백만 남긴다 (로고마다 크기가 달라도 같은 상자에 맞게)."""
    from PIL import Image
    im = Image.open(src).convert("RGBA")
    box = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if box:
        im = im.crop(box)
    canvas = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    canvas.paste(im, (pad, pad))
    canvas.save(out)


def load(spec: dict | None = None) -> dict:
    """지시서에 맞는 스타일을 돌려준다: template, colors, font, 바탕색들, logo(경로 또는 None), academy."""
    spec = spec or {}
    if "brand" in spec:  # 미리보기·시험용 직접 지정
        a = {"name": spec.get("academy", "미리보기"), "template": spec["brand"].get("template", "h4"),
             "colors": {**DEFAULT_COLORS, **spec["brand"].get("colors", {})}, "id": None}
        logo = spec["brand"].get("logo")
        logo = Path(logo) if logo else None
    else:
        name = spec.get("academy") or DEFAULT_ACADEMY
        acads = _fetch_academies() or []
        a = next((x for x in acads if x["name"] == name), None)
        if not a:
            if name != DEFAULT_ACADEMY or acads:
                print(f"[스타일] '{name}' 학원을 찾지 못해 기본 스타일로 만듭니다.", flush=True)
            a = {"name": name, "template": "h4", "colors": dict(DEFAULT_COLORS), "id": None}
        logo = CACHE / f"{a['id']}_로고.png" if a.get("id") and a.get("hasLogo") else None
        if logo is None and name == DEFAULT_ACADEMY:
            logo = ROOT / "로고" / "로고_투명.png"
    tpl = dict(TEMPLATES.get(a.get("template"), TEMPLATES["h4"]))
    colors = {**DEFAULT_COLORS, **(a.get("colors") or {})}
    if tpl.pop("derive", False):  # 학원색 바탕: 강조색을 아주 어둡게 눌러 바탕으로 쓴다
        base = colors["accent"]
        tpl.update(navy=mix(base, "000000", 0.86), card=mix(base, "000000", 0.76), slate=mix(base, "000000", 0.66),
                   dim=mix(base, "FFFFFF", 0.45), panel=mix(base, "000000", 0.88), end=mix(base, "000000", 0.92))
    fixed = {k: readable_on_dark(v, tpl["card"]) for k, v in colors.items()}
    for k in colors:
        if fixed[k] != colors[k]:
            print(f"[스타일] {a['name']}의 {k} 색 #{colors[k]}은 어두운 바탕에서 안 보여 #{fixed[k]}로 밝혀 씁니다.", flush=True)
    return {"academy": a["name"], "template": a.get("template", "h4"), "colors": fixed, "logo": logo, **tpl}


def apply(b: dict) -> None:
    """make_reel.COLORS 의 색 이름을 이 학원 색으로 바꿔 끼운다. shortform2 를 불러온 뒤에 부를 것."""
    import make_reel as m
    m.COLORS.update(yellow=b["colors"]["accent"], green=b["colors"]["english"], orange=b["colors"]["point"],
                    navy=b["navy"], card=b["card"], ink=b["navy"], slate=b["slate"], dim=b["dim"])
    print(f"[스타일] {b['academy']} · {TEMPLATES.get(b['template'], TEMPLATES['h4'])['name']} · 글꼴 {b['font']}", flush=True)


def ass_bgr(h: str) -> str:
    """RRGGBB → ASS 색(&HBBGGRR&)."""
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&"


def logo_place(logo: Path) -> tuple[int, int, int]:
    """로고를 상자에 맞춘 폭과 왼쪽 위 좌표 (폭, x, y)."""
    from PIL import Image
    w0, h0 = Image.open(logo).size
    w = min(LOGO_BOX_W, LOGO_BOX_H * w0 / h0)
    h = w * h0 / w0
    w = int(round(w)) // 2 * 2
    return w, int(LOGO_CX - w / 2), int(round(LOGO_CY - h / 2))
