#!/usr/bin/env python
"""완료(전달)된 지 7일이 지난 제출의 원본 영상과 받아쓰기 작업 폴더를 내 PC에서 지운다.

제출받기.py --watch 가 5분마다 함께 부른다. 따로 돌릴 때:
  .venv\\Scripts\\python 정리하기.py            # 지울 것을 지금 지운다
  .venv\\Scripts\\python 정리하기.py --dry-run  # 무엇을 지울지 보기만

지우는 것: 원본/제출/<학원>/<받은 파일>  과  work/<받은 파일 이름>/ (받아쓰기·중간 파일)
남기는 것: 완성/ 의 릴스 (드라이브에도 있음), 직접 만든 다른 work/ 폴더
기준: 관리자 페이지 상태가 '완료(전달)'이고 전달(또는 완료로 바꾼) 시각이 7일 지남.
      상태를 다시 '작업 중' 등으로 돌리면 지우지 않는다.
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import deliver
import submit_status as ss

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "원본" / "제출"
WORK = ROOT / "work"
KEEP_DAYS = 7


def _inside(p: Path, base: Path) -> bool:
    try:
        p.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def targets(items: list[dict], now: datetime | None = None) -> list[tuple[dict, list[Path]]]:
    """지울 제출과 지울 경로들. items 는 /api/admin/records 의 items."""
    now = now or datetime.now(timezone.utc)
    by_key = {e["key"]: e for e in ss.received()}
    out = []
    for it in items:
        if it.get("status") != "done":
            continue
        when = it.get("delivered") or it.get("changed")
        try:
            t = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
        except ValueError:
            continue
        if now - t < timedelta(days=KEEP_DAYS):
            continue
        e = by_key.get(it.get("key"))
        if not e:
            continue
        raw = RAW / e["file"]
        paths = [p for p in (raw, WORK / raw.stem) if p.exists()]
        # 안전: 원본/제출 과 work 바깥은 절대 지우지 않는다
        paths = [p for p in paths if (_inside(p, RAW) and p.is_file()) or (_inside(p, WORK) and p.parent.resolve() == WORK.resolve())]
        if paths:
            out.append((it, paths))
    return out


def run(dry: bool = False) -> int:
    items = deliver.api("/api/admin/records")["items"]
    n = 0
    for it, paths in targets(items):
        print(f"PC 정리: {it.get('academyName')} / {it.get('name')} / {it.get('title')}", flush=True)
        for p in paths:
            print(f"  {'지울 것' if dry else '지움'}: {p.relative_to(ROOT)}", flush=True)
            if not dry:
                try:
                    shutil.rmtree(p) if p.is_dir() else p.unlink()
                except OSError as ex:  # 다른 프로그램이 열어 둔 파일 등: 다음에 다시
                    print(f"  못 지움({ex}) — 다음 확인 때 다시 합니다", flush=True)
                    continue
        n += 1
    return n


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    print(f"정리 {'대상' if dry else '완료'} {run(dry)}건")
