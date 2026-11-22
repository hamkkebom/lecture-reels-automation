#!/usr/bin/env python
"""후보 구간을 넉넉하게 잘라 단어별 시각을 받아쓴다 (정확한 시작·끝 단어를 고르기 위한 준비).

  .venv\\Scripts\\python rough.py 원본/그래머머스트_1강_1부.mp4 A4:464:563 A6:1344:1420 ...

결과: work/clips/<이름>/rough_words.json (시각은 원본 기준 초)
"""
from __future__ import annotations

import json
import sys
import time

import make_reel as m

HINT = "영어 문법 강의. 주어, 동사, 수일치, 단수, 복수, 명사절, 관계대명사, 선행사, 완전절, 불완전절, 간접의문문, 수식어, 형용사구, 하이픈, 대시, that, who, running, be동사"


def main() -> None:
    src = m.ROOT / sys.argv[1]
    for item in sys.argv[2:]:
        name, s, e = item.split(":")
        t0 = time.time()
        work = m.ROOT / "work" / "clips" / name
        work.mkdir(parents=True, exist_ok=True)
        rough = work / "rough.mp4"
        m.run_tool("cut", src, "--start", s, "--end", e, "--smart", "-o", rough, "--overwrite")
        words = m.transcribe(rough, work, "large-v3-turbo", "ko", HINT, "auto")
        for w in words:
            w["start"] = round(w["start"] + float(s), 2)
            w["end"] = round(w["end"] + float(s), 2)
        (work / "rough_words.json").write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"=== {name}: 단어 {len(words)}개, 걸린 시간 {time.time() - t0:.0f}초", flush=True)


if __name__ == "__main__":
    main()
