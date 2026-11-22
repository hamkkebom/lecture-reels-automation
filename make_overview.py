#!/usr/bin/env python
"""만든 릴스를 한 장(A4 가로)으로 정리한다.

  .venv\\Scripts\\python make_overview.py

결과: 한눈에보기/제작현황.html (+ 대표 장면 그림). PDF 는 브라우저 인쇄 기능으로 만든다.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import batch_reels as br
import make_reel as m
import shortform as sf
import shortform2 as s2

OUT = m.ROOT / "한눈에보기"
# (클립 이름, 결과 파일, 덮는 그래픽, 표시)  표시: 앞 = 추천 구간의 앞부분만, 추 = 자막 일부를 추정으로 고침
CLIPS = [
    ("1부_01_if", None, "동사 표 · 금지 카드", ""),
    ("1부_02_if_will", "1부_02_if_will_시안H4_그래픽", "공식 카드 2 · 금지 카드", "기준"),
    ("1부_03_동명사주어", None, "문제 카드 · 바꿔 쓰기 표", ""),
    ("1부_04_whoyouare", None, "의·주·동 표", ""),
    ("1부_05_fact", None, "문제 카드 · 정답 카드", ""),
    ("1부_06_수일치원리", None, "없음 (자막 · 요약 띠만)", ""),
    ("1부_07_room", None, "금지 · 문제 · 정답 카드", "추"),
    ("1부_08_dash", None, "하이픈 표 · 콤마·대시 표", "추"),
    ("1부_09_running", None, "공식 카드 · 비교 표", "앞"),
    ("1부_10_that", None, "공식 카드 2 · 정리표", "앞추"),
    ("2편_01_herewego", None, "문제 카드 · 정리표", ""),
    ("2편_02_근자일치", None, "원칙 카드 · 예외 카드", "추"),
    ("2편_03_neither", None, "문제 · 짝 표 · 정답 카드", ""),
    ("2편_04_number", None, "공식 카드 2 · 정리표", ""),
    ("2편_05_띵원바디", None, "자리 비교 표 · 공식 카드", ""),
    ("2편_06_상관접속사", None, "유형 카드 3", "추"),
    ("2편_07_each", None, "공식 · 예문 문제 · 끝말 표", ""),
]


def mmss(t: float) -> str:
    return f"{int(t) // 60}:{int(t) % 60:02d}"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    cfg = {c["name"]: c for c in br.CFG["clips"]}
    cards, total = [], 0.0
    for name, fname, graphics, flag in CLIPS:
        video = m.ROOT / "output" / f"{fname or name + '_그래픽'}.mp4"
        dur = m.run_tool("probe", video, "--json", capture=True)["duration"]
        total += dur
        s, e = br.bounds(cfg[name])
        spec_file = m.ROOT / (f"그래픽_{name}.json" if not fname else "숏폼5_if_will.json")
        spec = json.loads(spec_file.read_text(encoding="utf-8"))
        # 대표 장면: 아래 요약 띠가 뜬 직후 (강사와 자막, 요약이 함께 보이는 때)
        words = json.loads((m.ROOT / "work" / name / "words_fixed.json").read_text(encoding="utf-8"))
        raw = s2.parse_script(spec["script"]) if "script" in spec else spec["chunks"]
        chunks = s2.index_chunks(sf.align(words, [c[:4] for c in raw]))
        lower = spec.get("lower", [])
        at = chunks[lower[0]["at_chunk"]]["start"] + 1.2 if lower else dur * 0.5
        thumb = OUT / f"{name}.png"
        m.run_tool("look", video, "--at", f"{min(at, dur - 0.5):.2f}", "--width", "360", "-o", thumb, "--overwrite")
        part, num = name.split("_")[0], name.split("_")[1]
        title = spec["title1"].replace("*", "")
        tags = "".join(f'<span class="tag {k}">{t}</span>' for k, t in
                       [("std", "기준 편"), ("front", "앞부분만"), ("guess", "추정 교정")]
                       if {"std": "기준", "front": "앞", "guess": "추"}[k] in flag)
        cards.append(f"""<div class="card {'p2' if part == '2편' else 'p1'}">
 <div class="strip"><div class="no"><b>{num}</b><span>{part}</span></div>
  <div class="shot"><img src="{html.escape(thumb.name)}"></div>
  <div class="len"><b>{round(dur)}</b><span>초</span></div></div>
 <div class="body"><h3>{html.escape(title)}</h3>
  <p class="src">원본 {mmss(s)} ~ {mmss(e)}</p>
  <p class="gfx">{html.escape(graphics)}</p>{tags}</div></div>""")
    n1 = sum(1 for c in CLIPS if c[0].startswith("1부"))
    page = TEMPLATE.replace("{{CARDS}}", "\n".join(cards)).replace("{{N}}", str(len(CLIPS))) \
        .replace("{{N1}}", str(n1)).replace("{{N2}}", str(len(CLIPS) - n1)) \
        .replace("{{TOTAL}}", f"{int(total) // 60}분 {int(total) % 60}초").replace("{{AVG}}", str(round(total / len(CLIPS))))
    (OUT / "제작현황.html").write_text(page, encoding="utf-8")
    print(f"완료: {OUT / '제작현황.html'} / {len(CLIPS)}편, 합계 {total:.0f}초")


TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>릴스 제작 현황</title>
<style>
@page { size: A4 landscape; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: 297mm; height: 210mm; }
body { font-family: "Pretendard", "Malgun Gothic", sans-serif; color: #141c2b; background: #fff;
  padding: 8mm 9mm 6mm; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
header { display: flex; align-items: flex-end; justify-content: space-between; height: 15mm;
  border-bottom: 0.6mm solid #141c2b; padding-bottom: 2.4mm; }
h1 { font-size: 17pt; font-weight: 800; letter-spacing: -0.02em; }
h1 small { font-size: 8.5pt; font-weight: 600; color: #5b6880; margin-left: 3mm; letter-spacing: 0; }
.stats { display: flex; gap: 6mm; }
.stats div { text-align: right; line-height: 1.15; }
.stats b { font-size: 14pt; font-weight: 800; }
.stats span { display: block; font-size: 6.5pt; color: #5b6880; font-weight: 600; }
main { display: grid; grid-template-columns: repeat(6, 1fr); grid-template-rows: repeat(3, 1fr); gap: 2.6mm;
  height: 170mm; margin-top: 3mm; }
.card { border: 0.3mm solid #cfd6e2; border-radius: 2mm; overflow: hidden; display: flex; flex-direction: column; }
.strip { background: #0c1424; height: 31mm; display: flex; align-items: center; justify-content: space-between;
  padding: 0 2.6mm; flex: none; }
.shot { width: 24.4mm; height: 31mm; overflow: hidden; }
.shot img { width: 24.4mm; display: block; margin-top: -4.6mm; }
.no, .len { width: 8mm; color: #fff; text-align: center; line-height: 1.1; }
.no b { font-size: 15pt; font-weight: 800; display: block; }
.no span { font-size: 6.5pt; font-weight: 700; padding: 0.4mm 1.3mm; border-radius: 1.4mm; color: #0c1424; }
.p1 .no span { background: #ffd400; }
.p2 .no span { background: #5be0c8; }
.len b { font-size: 12pt; font-weight: 800; display: block; }
.len span { font-size: 6.5pt; color: #9fb0cc; font-weight: 600; }
.body { padding: 2mm 2.4mm 1.6mm; flex: 1; }
h3 { font-size: 8.6pt; font-weight: 800; line-height: 1.25; letter-spacing: -0.02em; min-height: 7.6mm; }
p { font-size: 6.6pt; line-height: 1.35; color: #3c4960; }
p.src { color: #7a879d; margin-top: 0.8mm; }
p.gfx { margin-top: 0.3mm; font-weight: 600; }
.tag { display: inline-block; font-size: 5.8pt; font-weight: 700; padding: 0.3mm 1.4mm; border-radius: 1.3mm;
  margin: 1mm 1mm 0 0; }
.tag.std { background: #141c2b; color: #fff; }
.tag.front { background: #ffe9c7; color: #8a4b00; }
.tag.guess { background: #ffd9d6; color: #96231b; }
.note { border: 0.3mm dashed #b5bfd0; border-radius: 2mm; padding: 2.6mm; display: flex; flex-direction: column;
  justify-content: center; gap: 1.6mm; }
.note h3 { min-height: 0; font-size: 8pt; }
.note p { font-size: 6.4pt; }
footer { font-size: 6.2pt; color: #7a879d; margin-top: 1.6mm; display: flex; justify-content: space-between; }
</style></head><body>
<header><h1>릴스 제작 현황<small>그래머 머스트 1강 · 그래픽 방식 · 2026-11-20</small></h1>
<div class="stats"><div><b>{{N}}편</b><span>추천 구간 전부</span></div><div><b>{{N1}} + {{N2}}</b><span>1부 + 2편</span></div>
<div><b>{{TOTAL}}</b><span>합계 길이</span></div><div><b>{{AVG}}초</b><span>편당 평균</span></div></div></header>
<main>
{{CARDS}}
<div class="note"><h3>표시 읽는 법</h3>
<p><span class="tag std">기준 편</span>이 방식을 처음 확정한 편</p>
<p><span class="tag front">앞부분만</span>추천 구간이 길어 앞 한 덩어리만 사용</p>
<p><span class="tag guess">추정 교정</span>받아쓰기를 문맥으로 고친 자막이 있음. 들어 보고 확인 필요</p>
<p>가운데 그림은 각 편의 한 장면, 오른쪽 숫자는 길이입니다.</p></div>
</main>
<footer><span>파일 위치: 바탕화면 / 릴스_그래픽시안 · 원본 위치는 각 강의 영상 안의 시각</span>
<span>모든 편: 화면 고정, 말 자르지 않음, 규격 검사 통과 · 소리와 움직임은 직접 확인 필요</span></footer>
</body></html>
"""

if __name__ == "__main__":
    main()
