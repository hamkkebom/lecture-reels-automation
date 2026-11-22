#!/usr/bin/env python
"""구조를 바꾼 숏폼 편집.

  .venv\\Scripts\\python shortform2.py 숏폼2_if_will.json

shortform.py 와 다른 점:
  - 군더더기 문구를 영상에서 잘라 내 호흡을 빠르게 한다 (chunks 의 마지막 값 0).
  - 잘린 자리마다 확대 단계를 바꿔 점프컷으로 만든다 (3단계).
  - 위쪽에 단계 표시(①, ②)가 바뀌며 뜬다.
  - 규칙을 말하는 대목은 강의 화면을 그래픽 화면으로 잠깐 덮는다 (cutaways).
  - 끝에 정리 화면을 붙인다 (end_card).
준비물: work/<clip>/02_framed_43.mp4, words_fixed.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import make_reel as m
import shortform as sf

W, H = m.W, m.H
TOP, BOTTOM = (H - W * 3 // 4) // 2, (H + W * 3 // 4) // 2  # 4:3 영상이 놓인 세로 범위
FPS = 30


def fr(t: float) -> float:
    return round(t * FPS) / FPS


def build_pieces(chunks: list[dict], duration: float) -> list[dict]:
    """사용하는 문구를 이어지는 덩어리(조각)로 묶는다. 버린 문구나 확대 단계가 바뀌는 곳에서 조각이 끊긴다."""
    pieces: list[dict] = []
    for k, c in enumerate(chunks):
        if not c["keep"]:
            continue
        prev = chunks[k - 1] if k else None
        joined = bool(pieces) and prev is not None and prev["keep"] and prev["zoom"] == c["zoom"]
        if joined:
            pieces[-1]["chunks"].append(c)
        else:
            pieces.append({"chunks": [c], "zoom": c["zoom"], "after_drop": prev is not None and not prev["keep"]})
    for p in pieces:
        first, last = p["chunks"][0], p["chunks"][-1]
        k_last = chunks.index(last)
        nxt = chunks[k_last + 1] if k_last + 1 < len(chunks) else None
        start = first["start"] - 0.06
        if p is pieces[0] and start < 0.5:  # 맨 앞의 짧은 숨은 자르지 않는다 (다시 인코딩할 일이 없어진다)
            start = 0.0
        if nxt is None:
            end = min(last["end"] + 0.25, duration)
        elif nxt["keep"]:  # 바로 이어지는 문구(확대만 바뀜): 틈 없이 붙인다
            end = nxt["start"] - 0.06
        else:              # 다음 문구는 버림: 말이 끝난 직후에서 자른다
            end = min(last["end"] + 0.16, nxt["start"] + 0.02)
        p["a"], p["b"] = max(0.0, fr(start)), fr(end)
    out_t = 0.0
    for p in pieces:  # 새 영상에서의 시작 시각
        p["offset"] = out_t
        out_t += p["b"] - p["a"]
        for c in p["chunks"]:
            c["new_start"] = p["offset"] + (c["start"] - p["a"])
            c["new_end"] = p["offset"] + (c["end"] - p["a"])
            c["piece_end"] = out_t
            for w in c["words"]:
                w["new_start"] = p["offset"] + (w["start"] - p["a"])
    return pieces


def render_pieces(src: Path, work: Path, pieces: list[dict], levels: list[float]) -> Path:
    parts = []
    for k, p in enumerate(pieces):
        piece = work / f"h_{k:02d}.mp4"
        m.run_tool("cut", src, "--start", f"{p['a']:.3f}", "--end", f"{p['b']:.3f}", "--codec", "h264",
                   "-o", piece, "--overwrite")
        f = levels[p["zoom"]]
        if f > 1.001:
            cw, chh = int(W / f) // 2 * 2, int(H / f) // 2 * 2
            cy = min(max(0, 930 - chh // 2), H - chh)  # 얼굴이 있는 쪽으로 살짝 위를 기준 삼는다
            crop = work / f"h_{k:02d}_crop.mp4"
            m.run_tool("crop", piece, "-o", crop, "--x", (W - cw) // 2, "--y", cy, "--width", cw, "--height", chh,
                       "--overwrite")
            big = work / f"h_{k:02d}_big.mp4"
            m.run_tool("fit", crop, "-o", big, "--width", W, "--height", H, "--aspect", "9:16", "--fit", "crop",
                       "--fps", FPS, "--overwrite")
            piece = big
        parts.append(piece)
    out = work / "02h_joined.mp4"
    m.run_tool("join", *parts, "--transition", "none", "--width", W, "--height", H, "--fps", FPS,
               "-o", out, "--overwrite")
    return out


PANEL, END_PANEL, FONT = "&H1E120C&", "&H140C08&", "Pretendard ExtraBold"  # main()에서 학원 틀로 바뀜


def panel(t0: float, t1: float, color: str | None = None) -> str:
    """강의 화면(4:3 범위)을 덮는 어두운 판."""
    color = color or PANEL
    # 확대된 구간에서는 영상이 위아래로 조금 더 넓게 보이므로, 그만큼 넉넉하게 덮는다
    top, bottom = TOP - 18, BOTTOM + 86
    return (f"Dialogue: 5,{m.ass_time(t0)},{m.ass_time(t1)},Bar,,0,0,0,,"
            f"{{\\pos(0,{top})\\1c{color}\\fad(120,100)\\p1}}m 0 0 l {W} 0 {W} {bottom - top} 0 {bottom - top}{{\\p0}}")


# ----------------------------------------------------------- 디자인된 그래픽 화면
# 색 (RRGGBB). 남색 바탕 위에 카드, 그 위에 흰 상자·색 알약·결과 상자를 차례로 올린다.
NAVY, CARD, INK, DIM = "0C1424", "17243C", "0C1424", "6F82A6"
m.COLORS.update({"navy": NAVY, "card": CARD, "ink": INK, "dim": DIM, "slate": "24324F"})
PTOP, PBOT = TOP - 18, BOTTOM + 86          # 그래픽이 덮는 세로 범위
POP = "\\fscx45\\fscy45\\t(0,130,\\fscx108\\fscy108)\\t(130,220,\\fscx100\\fscy100)\\fad(70,0)"


def rrect(w: int, h: int, r: int) -> str:
    """모서리가 둥근 사각형 그림 경로 (왼쪽 위가 0,0)."""
    return (f"m {r} 0 l {w - r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h - r} b {w} {h} {w} {h} {w - r} {h} "
            f"l {r} {h} b 0 {h} 0 {h} 0 {h - r} l 0 {r} b 0 0 0 0 {r} 0")


def circle(r: int) -> str:
    k = round(r * 0.5523)
    d = 2 * r
    return (f"m {r} 0 b {r + k} 0 {d} {r - k} {d} {r} b {d} {r + k} {r + k} {d} {r} {d} "
            f"b {r - k} {d} 0 {r + k} 0 {r} b 0 {r - k} {r - k} 0 {r} 0")


def shape(t0: float, t1: float, path: str, cx: int, cy: int, color: str, anim: str = "", layer: int = 6,
          an: int = 5) -> str:
    return (f"Dialogue: {layer},{m.ass_time(t0)},{m.ass_time(t1)},Bar,,0,0,0,,"
            f"{{\\an{an}\\pos({cx},{cy})\\1c{m.ass_color(color)}{anim}\\p1}}{path}{{\\p0}}")


def label(t0: float, t1: float, text: str, cx: int, cy: int, size: int, color: str, anim: str = "",
          layer: int = 8, flat: bool = True) -> str:
    edge = "\\bord0\\shad0" if flat else ""
    return (f"Dialogue: {layer},{m.ass_time(t0)},{m.ass_time(t1)},Pop,,0,0,0,,"
            f"{{\\an5\\pos({cx},{cy})\\fs{size}\\1c{m.ass_color(color)}{edge}{anim}}}{m.esc(text)}")


def base_card(s: float, e: float, chip: str, chip_color: str) -> list[str]:
    """남색 바탕 + 둥근 카드 + 왼쪽 위 번호표."""
    mid = (PTOP + PBOT) // 2
    fade = "\\fad(120,110)"
    ev = [shape(s, e, f"m 0 0 l {W} 0 {W} {PBOT - PTOP} 0 {PBOT - PTOP}", W // 2, mid, "navy", fade, 5),
          shape(s, e, rrect(W - 90, PBOT - PTOP - 80, 44), W // 2, mid, "card", fade, 6)]
    if chip:
        cw = int(m.glyph_width(chip, 44)) + 76
        ev.append(shape(s + 0.05, e, rrect(cw, 72, 36), W // 2, PTOP + 112, chip_color, POP, 7))
        ev.append(label(s + 0.05, e, chip, W // 2, PTOP + 110, 44, "ink", POP))
    return ev


def designed(cut: dict, s: float, e: float, by_text: dict) -> list[str]:
    def when(key: str, default: float) -> float:
        name = cut.get(key)
        if isinstance(name, (int, float)):  # 숫자면 그 시각(초)
            return float(name)
        return by_text[name]["new_start"] if name else default

    accent = cut.get("accent", "yellow")
    ev = base_card(s, e, cut.get("chip", ""), accent)
    if cut["template"] == "define":
        # [ if ]  =  ( ~라면 )      ↓      [ 부사절 ]
        row = PTOP + 300
        # 첫 줄(상자 = 알약)은 한 덩어리로 보고 화면 가운데에 맞춘다
        gap, eq = 46, 60
        lfs = 124 if len(cut["left"]) <= 3 else 96
        rfs = 92
        bw = max(230, int(m.glyph_width(cut["left"], lfs)) + 80)
        pw = int(m.glyph_width(cut["right"], rfs)) + 96
        if bw + pw + 2 * gap + eq > 940:  # 긴 표현은 한 줄에 들어가게 함께 줄인다
            k = 940 / (bw + pw + 2 * gap + eq)
            lfs, rfs, gap = int(lfs * k), int(rfs * k), int(gap * k)
            bw = int(m.glyph_width(cut["left"], lfs)) + 64
            pw = int(m.glyph_width(cut["right"], rfs)) + 76
        x0 = (W - (bw + gap + eq + gap + pw)) // 2
        bx, ex, px = x0 + bw // 2, x0 + bw + gap + eq // 2, x0 + bw + gap + eq + gap + pw // 2
        ev.append(shape(s + 0.12, e, rrect(bw, 156, 30), bx, row, "white", POP, 7))
        ev.append(label(s + 0.12, e, cut["left"], bx, row - 6, lfs, "ink", POP))
        ev.append(label(s + 0.38, e, cut.get("op", "="), ex, row - 6, 110, "white", POP))
        t_r = when("right_chunk", s + 0.6)
        ev.append(shape(t_r, e, rrect(pw, 156, 78), px, row, accent, POP, 7))
        ev.append(label(t_r, e, cut["right"], px, row - 4, rfs, "ink", POP))
        t_res = when("result_chunk", s + 1.6)
        ev.append(shape(t_res - 0.12, e, "m 0 0 l 96 0 48 62", W // 2, PTOP + 468, "dim", "\\fad(150,0)", 7))
        ev.append(shape(t_res, e, rrect(700, 260, 40), W // 2, PTOP + 668, cut.get("result_color", "mint"), POP, 7))
        ev.append(label(t_res, e, cut["result"], W // 2, PTOP + 640, 150, "ink", POP))
        if cut.get("result_sub"):
            ev.append(label(t_res + 0.12, e, cut["result_sub"], W // 2, PTOP + 752, 42, "ink", "\\fad(200,0)"))
    elif cut["template"] == "ban":
        # 조건 한 줄 / 큰 단어에 빨간 줄이 그어짐 + X 도장 / 빨간 띠 문구
        ev.append(label(s + 0.12, e, cut["head"], W // 2, PTOP + 232, 66, accent, "\\fad(160,0)"))
        t_w = when("word_chunk", s + 0.5)
        t_b = when("ban_chunk", s + 1.6)
        wy = PTOP + 432
        ev.append(label(t_w, t_b, cut["word"], W // 2, wy, 250, "white", POP))
        ev.append(label(t_b, e, cut["word"], W // 2, wy, 250, "dim"))
        ww = int(m.glyph_width(cut["word"], 250) * 0.8) + 90  # 단어 폭보다 조금 길게
        ev.append(shape(t_b, e, f"m 0 0 l {ww} 0 {ww} 30 0 30", (W - ww) // 2, wy + 14, "red",
                        "\\fscx0\\t(0,170,\\fscx100)", 9, an=4))
        # 빨간 띠: [X 동그라미] + 문구를 한 덩어리로 보고 가운데에 맞춘다 (모든 줄이 같은 중심선에 선다)
        by = PTOP + 708
        ev.append(shape(t_b + 0.15, e, rrect(880, 170, 40), W // 2, by, "red", POP, 7))
        tw = int(m.glyph_width(cut["ban"], 100))
        icon, gap = 104, 30
        x0 = (W - (icon + gap + tw)) // 2
        stamp = "\\fscx40\\fscy40\\frz-40\\t(80,220,\\fscx112\\fscy112\\frz8)\\t(220,310,\\fscx100\\fscy100\\frz0)\\fad(60,0)"
        ev.append(shape(t_b + 0.25, e, circle(icon // 2), x0 + icon // 2, by, "white", stamp, 9))
        ev.append(label(t_b + 0.25, e, "X", x0 + icon // 2, by - 3, 78, "red", stamp, layer=10))
        ev.append(label(t_b + 0.15, e, cut["ban"], x0 + icon + gap + tw // 2, by - 5, 100, "white", POP))
    elif cut["template"] == "rows":
        # 정리표: [색 알약 | 내용] 줄이 말하는 순서대로 쌓이고, 맨 아래에 결론 띠
        rows = cut["rows"]
        y0, step = {3: (PTOP + 236, 172), 4: (PTOP + 250, 166)}.get(len(rows), (PTOP + 300, 200))
        if len(rows) == 2 and not cut.get("note"):  # 두 줄뿐이면 카드 가운데로 내린다
            y0 = PTOP + 390
        left_edge, right_edge = (W - 920) // 2 + 26, (W + 920) // 2 - 26
        # 알약은 모두 같은 폭, 내용은 같은 왼쪽 선에서 시작한다 (줄마다 어긋나 보이지 않게)
        tw = max(int(m.glyph_width(r["tag"], 54)) for r in rows) + 60
        tx = left_edge + tw + 34
        room = right_edge - tx
        fs = min(70, min(int(70 * (room - 6) / m.glyph_width(r["text"], 70)) for r in rows))
        for i, r in enumerate(rows):
            t_r = max(s + 0.15, by_text[r["at_chunk"]]["new_start"] if r.get("at_chunk") else s + 0.15 + 0.5 * i)
            y = y0 + i * step
            ev.append(shape(t_r, e, rrect(920, 150, 36), W // 2, y, "slate", "\\fad(140,0)", 7))
            ev.append(shape(t_r, e, rrect(tw, 96, 48), left_edge + tw // 2, y, r.get("color", accent), POP, 8))
            ev.append(label(t_r, e, r["tag"], left_edge + tw // 2, y - 3, 54, "ink", POP, layer=9))
            ev.append(f"Dialogue: 9,{m.ass_time(t_r)},{m.ass_time(e)},Pop,,0,0,0,,"
                      f"{{\\an4\\pos({tx},{y - 4})\\fs{fs}\\1c{m.ass_color('white')}\\bord0\\shad0\\fad(140,0)}}"
                      f"{m.esc(r['text'])}")
        if cut.get("note"):
            t_n = max(s + 0.5, when("note_chunk", s + 0.3 + 0.5 * len(rows)))
            ny = y0 + len(rows) * step + (0 if len(rows) >= 3 else 20)
            nfs = min(74, int(74 * 800 / m.glyph_width(cut["note"], 74)))
            ev.append(shape(t_n, e, rrect(900, 136, 40), W // 2, ny, cut.get("note_color", "mint"), POP, 7))
            ev.append(label(t_n, e, cut["note"], W // 2, ny - 4, nfs, "ink", POP))
    elif cut["template"] == "quiz":
        # 조건 한 줄 / 문장 / [보기 1] [보기 2] -> 답이 초록으로, 오답은 줄이 그어짐 / 결론 띠
        soft = "\\fad(160,0)"
        if cut.get("head"):
            ev.append(label(s + 0.12, e, cut["head"], W // 2, PTOP + 214, 54, accent, soft))
        if cut.get("sentence"):
            fs = min(84, int(84 * 880 / m.glyph_width(cut["sentence"], 84)))
            ev.append(label(s + 0.2, e, cut["sentence"], W // 2, PTOP + 318, fs, "white", POP))
        opts, ans = cut["options"], cut["answer"]
        # answer 가 null 이면 문제만 내고 답은 밝히지 않는다. answer_at 은 그래픽이 뜬 뒤 몇 초에 답을 밝힐지.
        t_a = e if ans is None else when("answer_chunk", s + cut.get("answer_at", 1.6))
        ofs = min(96, int(96 * 380 / max(m.glyph_width(o, 96) for o in opts)))
        widths = [max(300, int(m.glyph_width(o, ofs)) + 100) for o in opts]
        gap, oy = 56, PTOP + 506
        x = (W - (sum(widths) + gap * (len(opts) - 1))) // 2
        for i, (o, bw) in enumerate(zip(opts, widths)):
            cx = x + bw // 2
            x += bw + gap
            t_o = max(s + 0.3, min(when(f"option{i + 1}_chunk", s + 0.45 + 0.22 * i), t_a - 0.2))
            ev.append(shape(t_o, t_a, rrect(bw, 170, 36), cx, oy, "white", POP, 7))
            ev.append(label(t_o, t_a, o, cx, oy - 5, ofs, "ink", POP))
            if ans is None:
                continue
            if i == ans:
                ev.append(shape(t_a, e, rrect(bw, 170, 36), cx, oy, "green", POP, 7))
                ev.append(label(t_a, e, o, cx, oy - 5, ofs, "ink", POP))
            else:
                ev.append(shape(t_a, e, rrect(bw, 170, 36), cx, oy, "slate", "", 7))
                ev.append(label(t_a, e, o, cx, oy - 5, ofs, "dim"))
                sw = bw - 70
                ev.append(shape(t_a, e, f"m 0 0 l {sw} 0 {sw} 16 0 16", cx - sw // 2, oy + 4, "red",
                                "\\fscx0\\t(0,170,\\fscx100)", 9, an=4))
        if cut.get("note"):
            t_n = max(s + 0.5, when("note_chunk", (s + 1.2) if ans is None else t_a + 0.35))
            nfs = min(78, int(78 * 800 / m.glyph_width(cut["note"], 78)))
            ev.append(shape(t_n, e, rrect(900, 150, 40), W // 2, PTOP + 736, cut.get("note_color", "mint"), POP, 7))
            ev.append(label(t_n, e, cut["note"], W // 2, PTOP + 731, nfs, "ink", POP))
    return ev


def pop_text(t0: float, t1: float, text: str, y: int, size: int, color: str, extra: str = "", layer: int = 6) -> str:
    pop = "\\fscx50\\fscy50\\t(0,120,\\fscx118\\fscy118)\\t(120,210,\\fscx100\\fscy100)"
    return (f"Dialogue: {layer},{m.ass_time(t0)},{m.ass_time(t1)},Pop,,0,0,0,,"
            f"{{\\pos({W // 2},{y})\\fs{size}\\1c{m.ass_color(color)}{pop}{extra}}}{m.esc(text)}")


TINT = {"y": "yellow", "m": "mint", "o": "orange", "r": "red", "g": "green", "x": "gray", "w": ""}


def parse_script(lines: list[str]) -> list[list]:
    """짧게 적은 자막 대본을 chunks 로 푼다.

    문구는 ' / ' 로 나눈다. 강조할 문구는 앞에 '종류.색:' 을 붙인다 (예: 'k.r:절대로 안 돼.').
    종류 q 질문, k 핵심, t 용어, a 혼잣말, n 보통 / 색 y m o r g x(회색) w(흰색).
    """
    out = []
    for part in " / ".join(lines).split(" / "):
        part = part.strip()
        if not part:
            continue
        kind, color = "n", ""
        if len(part) > 4 and part[1] == "." and part[3] == ":" and part[0] in "qktan" and part[2] in TINT:
            kind, color, part = part[0], TINT[part[2]], part[4:].strip()
        out.append([part, kind, color, 0, 1])
    return out


def index_chunks(chunks: list[dict]) -> dict:
    """문구로 자막 덩어리를 찾는 표. 같은 문구가 여러 번 나오면 '문구#2' 처럼 몇 번째인지 붙여 가리킨다."""
    table, seen = {}, {}
    for c in chunks:
        n = seen[c["text"]] = seen.get(c["text"], 0) + 1
        table.setdefault(c["text"], c)
        table[f"{c['text']}#{n}"] = c
    return table


def main() -> None:
    global PANEL, END_PANEL, FONT
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    import brand  # 학원별 틀·색 (지시서의 "academy", 없으면 승리어학원)
    B = brand.load(spec)
    brand.apply(B)
    PANEL, END_PANEL, FONT = brand.ass_bgr(B["panel"]), brand.ass_bgr(B["end"]), B["font"]
    work = m.ROOT / "work" / spec["clip"]
    framed = work / "02_framed_43.mp4"
    words = json.loads((work / "words_fixed.json").read_text(encoding="utf-8"))
    if "script" in spec:
        spec["chunks"] = parse_script(spec["script"])
    chunks = sf.align(words, [c[:4] for c in spec["chunks"]])
    for c, raw in zip(chunks, spec["chunks"]):
        c["zoom"], c["keep"] = int(raw[3]), bool(raw[4])
    if "--plan" in sys.argv:  # 문구별 시각만 보여 주고 끝낸다 (그래픽 넣을 자리를 정할 때 쓴다)
        for c in chunks:
            print(f"{c['start']:6.1f}-{c['end']:5.1f}  {c['kind']} {c['text']}")
        return
    t0 = time.time()

    src_dur = m.run_tool("probe", framed, "--json", capture=True)["duration"]
    pieces = build_pieces(chunks, src_dur)
    body = sum(p["b"] - p["a"] for p in pieces)
    print(f"조각 {len(pieces)}개, 본문 {body:.1f}초 (원래 {src_dur:.1f}초)")

    video = work / "02h_joined.mp4"
    if len(pieces) == 1 and pieces[0]["zoom"] == 0 and pieces[0]["a"] == 0:
        # 자르는 곳도 확대도 없으면 원래 영상을 그대로 쓴다 (화면이 한 번도 움직이지 않는다)
        print("확대·컷 없음: 원래 화면 그대로 사용")
        video = framed
    elif video.is_file() and "--recut" not in sys.argv:
        print(f"앞서 만든 {video.name} 재사용 (자르는 자리를 바꿨으면 --recut)")
    else:
        video = render_pieces(framed, work, pieces, spec.get("zoom_levels", [1.0, 1.15, 1.25]))
    got = m.run_tool("probe", video, "--json", capture=True)["duration"]
    if abs(got - body) > 0.12:
        print(f"주의: 이어 붙인 길이 {got:.2f}초가 계산값 {body:.2f}초와 다릅니다. 자막이 밀릴 수 있습니다.")
    end = spec.get("end_card")
    if end:  # 마지막 화면을 멈춰 정리 화면을 올릴 자리를 만든다
        held = work / "02h_held.mp4"
        m.run_tool("freeze", video, "--hold", end["hold"], "-o", held, "--overwrite")
        video = held
    duration = m.run_tool("probe", video, "--json", capture=True)["duration"]

    a = argparse.Namespace(
        title1=spec["title1"], title2="", title2_plain=False, title_color="yellow", title_size=84, title_y=292,
        caption_y=1400, caption_size=62, font=FONT, box_alpha="60", box=False, typewriter=False,
        hl=[], english_color=None, pop_size=92, pop_y=1215, pop_active="yellow", progress_bar=True)
    ass = m.build_ass([], duration, a, (TOP, BOTTOM), None).rstrip("\n").split("\n")
    at = ass.index("[Events]")
    ass.insert(at - 1, f"Style: Card,{FONT},54,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
                       "-1,0,0,0,100,100,0,0,3,16,0,5,30,30,0,1")
    by_text = index_chunks(chunks)
    ev: list[str] = []

    # 그래픽 화면(컷어웨이): 그 구간의 자막은 그래픽 안 글자가 대신한다
    hidden: set[int] = set()
    for cut in spec.get("cutaways", []):
        c0, c1 = by_text[cut["from_chunk"]], by_text[cut["to_chunk"]]
        k1 = chunks.index(c1)
        after = next((c for c in chunks[k1 + 1:] if c["keep"]), None)
        # 다음 문구가 시작되기 직전에 걷어 낸다 (강사가 화면에 돌아오는 때와 맞추기 위함)
        e = min(after["new_start"] - 0.1, c1["new_end"] + 0.5) if after else min(c1["piece_end"], c1["new_end"] + 0.35)
        s = c0["new_start"] - 0.05
        # 강사가 화면에서 나가는/돌아오는 시각을 시트에서 읽어 직접 적을 수 있다 (초)
        s, e = cut.get("start_at", s), cut.get("end_at", e)
        for k in range(chunks.index(c0), k1 + 1):
            hidden.add(k)
        if cut.get("template"):  # 디자인된 그래픽 화면
            ev += designed(cut, s, e, by_text)
            continue
        ev.append(panel(s, e))
        # 말이 짧은 구간에서도 마지막 줄이 0.6초는 보이도록, 지시서의 등장 시각을 구간 길이에 맞춰 줄인다
        latest = max(max(ln.get("at", 0), ln.get("strike_at") or 0) for ln in cut["lines"])
        k_t = min(1.0, max(0.2, (e - s - 0.6) / latest)) if latest else 1.0
        for ln in cut["lines"]:
            # at_chunk 가 있으면 그 문구를 말하는 순간에 맞춰 등장한다
            ls = by_text[ln["at_chunk"]]["new_start"] if ln.get("at_chunk") else s + ln.get("at", 0) * k_t
            y = TOP + ln["y"]
            if ln.get("strike_chunk"):
                ln = dict(ln, strike_at=by_text[ln["strike_chunk"]]["new_start"] - s)
                k_s = 1.0
            else:
                k_s = k_t
            if ln.get("strike_at") is not None:  # 처음엔 그대로 보였다가, 줄이 그어지며 회색으로
                mid = s + ln["strike_at"] * k_s
                ev.append(pop_text(ls, mid, ln["text"], y, ln["size"], ln["color"]))
                ev.append(f"Dialogue: 6,{m.ass_time(mid)},{m.ass_time(e)},Pop,,0,0,0,,"
                          f"{{\\pos({W // 2},{y})\\fs{ln['size']}\\s1\\1c&H8C8C8C&\\frz-4\\t(0,90,\\frz3)\\t(90,180,\\frz0)}}"
                          f"{m.esc(ln['text'])}")
            else:
                extra = "\\3c&HFFFFFF&\\bord9\\t(210,270,\\frz-3)\\t(270,330,\\frz3)\\t(330,390,\\frz0)" if ln.get("shake") else ""
                ev.append(pop_text(ls, e, ln["text"], y, ln["size"], ln["color"], extra))

    # 자막
    kept = [(k, c) for k, c in enumerate(chunks) if c["keep"]]
    for i, (k, c) in enumerate(kept):
        if k in hidden:
            continue
        nxt = kept[i + 1][1]["new_start"] if i + 1 < len(kept) else body
        stop = min(max(c["new_end"] + 0.25, c["new_start"] + 0.5), nxt - 0.01, c["piece_end"] if nxt > c["piece_end"] else nxt)
        view = dict(c, start=c["new_start"], end=c["new_end"],
                    words=[dict(w, start=w["new_start"]) for w in c["words"]])
        if stop > view["start"]:
            body_text = sf.chunk_event(view, stop, a.pop_y)
            size = sf.SIZE[c["kind"]]
            need = m.glyph_width(c["text"], size) * 1.08  # 긴 영어 문장은 화면 폭에 맞게 글자를 줄인다
            if need > 990:
                body_text = body_text.replace(f"\\fs{size}", f"\\fs{int(size * 990 / need)}", 1)
            ev.append(f"Dialogue: 3,{m.ass_time(view['start'])},{m.ass_time(stop)},Pop,,0,0,0,,{body_text}")

    # 단계 표시: 제목 아래에서 내려와 다음 표시가 나올 때까지 남는다
    labels = spec.get("labels", [])
    for i, lb in enumerate(labels):
        s = by_text[lb["from_chunk"]]["new_start"]
        e = by_text[labels[i + 1]["from_chunk"]]["new_start"] if i + 1 < len(labels) else body
        ev.append(f"Dialogue: 2,{m.ass_time(s)},{m.ass_time(e)},Card,,0,0,0,,"
                  f"{{\\move({W // 2},{TOP - 300},{W // 2},{TOP - 222},0,200)\\fad(120,120)\\1c&H000000&"
                  f"\\3c{m.ass_color(lb['color'])}}}{m.esc(lb['text'])}")

    # 아래 검은 띠 그래픽: 사람을 가리지 않고, 말하는 순간에 맞춰 올라와 정해진 때까지 남는다
    for g in spec.get("lower", []):
        s = by_text[g["at_chunk"]]["new_start"] + 0.1
        e = by_text[g["until_chunk"]]["new_start"] if g.get("until_chunk") else duration
        y = BOTTOM + g["y"]
        col = m.ass_color(g["color"])
        move = f"\\move({W // 2},{y + 50},{W // 2},{y},0,200)\\fad(120,120)"
        if g.get("card"):
            ev.append(f"Dialogue: 2,{m.ass_time(s)},{m.ass_time(e)},Card,,0,0,0,,{{{move}\\fs50\\3c{col}}}{m.esc(g['text'])}")
            continue
        text = m.esc(g["text"])
        if g.get("strike"):  # 금지되는 단어는 회색으로 줄을 그어 앞에 붙인다
            text = f"{{\\s1\\1c&H9A9A9A&}}{m.esc(g['strike'])}{{\\s0\\1c{col}}} {text}"
        ev.append(f"Dialogue: 2,{m.ass_time(s)},{m.ass_time(e)},Pop,,0,0,0,,"
                  f"{{{move}\\fs{g['size']}\\1c{col}\\bord5}}{text}")

    # 정리 화면
    if end:
        ev.append(panel(body - 0.05, duration, END_PANEL))
        ev.append(pop_text(body, duration, end["header"], TOP + 130, 120, "white"))
        for i, row in enumerate(end["rows"]):
            y = TOP + 360 + i * 190
            s = body + 0.35 + i * 0.45
            ev.append(f"Dialogue: 6,{m.ass_time(s)},{m.ass_time(duration)},Card,,0,0,0,,"
                      f"{{\\move({W // 2 - 160},{y},{W // 2},{y},0,180)\\fad(120,0)\\fs58\\3c{m.ass_color(row['color'])}}}"
                      f"{m.esc(row['text'])}")

    ass_file = work / "overlay_h.ass"
    ass_file.write_text("\n".join(ass + ev) + "\n", encoding="utf-8-sig")
    titled = work / "03_titled_h.mp4"
    m.run_tool("caption", video, "--ass", ass_file, "-o", titled, "--overwrite")
    out = m.ROOT / "output" / f"{spec['clip']}_{spec['tag']}.mp4"
    m.run_tool("export", titled, "-o", out, "--preset", "reels", "--allow-long", "--normalize", "--overwrite")
    m.run_tool("look", out, "--tiles", "4x3", "--width", "1600", "-o", out.with_name(out.stem + "_sheet.png"), "--overwrite")
    try:
        m.run_tool("check", out, "--platform", "reels")
    except SystemExit as e:
        print(f"규격 검사 지적: {e}")
    m.save_timings(work, "h")
    print(f"완료: {out} / 길이 {duration:.1f}초 / 걸린 시간 {time.time() - t0:.0f}초")


if __name__ == "__main__":
    main()
