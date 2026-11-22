#!/usr/bin/env python
"""제출 영상의 진행 상태를 관리자 페이지에 알린다.

  .venv\\Scripts\\python submit_status.py --list                  # 받은 제출 목록
  .venv\\Scripts\\python submit_status.py <영상 파일|이름 일부> 작업중
  .venv\\Scripts\\python submit_status.py <영상 파일|이름 일부> 편집끝 --reels output\\a.mp4 output\\b.mp4 ...
  .venv\\Scripts\\python submit_status.py <영상 파일|이름 일부> 완료

편집끝 --reels: 완성 릴스를 완성/<학원>/<제출 이름>/ 에 모으고 개수를 관리자 페이지에 알린다
(정산 기준). 관리자 페이지의 '드라이브로 전달'은 이 폴더를 올린다.

다른 스크립트에서는 mark(path, "working") 처럼 부른다. 제출로 받은 영상이 아니거나
인터넷이 끊겨 있어도 작업은 멈추지 않는다 (알림만 건너뜀).
"""
from __future__ import annotations

import glob
import json
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "원본" / "제출" / "받은목록.jsonl"
DONE = ROOT / "완성"


def finished_dir(entry: dict) -> Path:
    """이 제출의 완성 릴스를 모으는 폴더: 완성/<학원>/<받은 파일 이름(확장자 뺌)>/"""
    return DONE / (entry.get("academyName") or "학원없음") / Path(entry["file"]).stem
ALIASES = {
    "작업중": "working", "작업": "working", "working": "working",
    "편집끝": "ready", "편집완료": "ready", "ready": "ready",
    "완료": "done", "전달": "done", "done": "done",
    "받음": "received", "received": "received",
}
LABEL = {"received": "PC로 받음", "working": "작업 중", "ready": "편집 끝(전달 전)", "done": "완료(전달)"}


def received() -> list[dict]:
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("key"):
            out.append(e)
    return out


def find(target: str | Path) -> dict | None:
    """파일 경로(이름), 또는 이름·강의 제목 일부로 받은 제출을 찾는다."""
    entries = received()
    name = Path(str(target)).name
    for e in entries:  # e["file"]은 '학원/파일명' (예전 기록은 파일명만)
        if Path(e["file"]).name == name or Path(e["file"]).stem == Path(name).stem:
            return e
    q = str(target).strip()
    hits = [e for e in entries if q and (q in e["file"] or q in e.get("name", "") or q in e.get("title", "")
                                         or q == e.get("academyName"))]
    return hits[-1] if len(hits) >= 1 and len({h["key"] for h in hits}) == 1 else None


def send(entry: dict, status: str | None, memo: str | None = None, **extra) -> None:
    cfg = json.loads((ROOT / "제출받기_설정.json").read_text(encoding="utf-8-sig"))
    body = {"id": entry["key"].split("/")[1], **extra}
    if status:
        body["status"] = status
    if memo is not None:
        body["memo"] = memo
    req = urllib.request.Request(cfg["url"].rstrip("/") + "/api/admin/status", data=json.dumps(body).encode(), method="POST",
                                 headers={"authorization": "Bearer " + cfg["token"], "content-type": "application/json",
                                          "user-agent": "Mozilla/5.0 (submit-fetcher)"})
    urllib.request.urlopen(req, timeout=20).close()


def mark(target: str | Path, status: str, memo: str | None = None) -> bool:
    """작업 스크립트용. 제출 영상이면 상태를 알리고 True. 아니거나 실패하면 False (예외 없음)."""
    try:
        e = find(target)
        if not e:
            return False
        send(e, ALIASES.get(status, status), memo)
        print(f"[관리자 페이지] {e.get('name')} / {e.get('title')} → {LABEL.get(ALIASES.get(status, status), status)}", flush=True)
        return True
    except Exception as ex:  # 알림 실패로 작업을 멈추지 않는다
        print(f"[관리자 페이지] 상태 알림 실패({ex}) — 작업은 계속합니다", flush=True)
        return False


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    if not args or args[0] == "--list":
        for e in received():
            print(f"- {e['file']}  ({e.get('received', '')})")
        sys.exit(0)
    reels: list[Path] = []
    if "--reels" in args:  # --reels 뒤의 것은 모두 릴스 파일 (와일드카드 가능)
        i = args.index("--reels")
        for pat in args[i + 1:]:
            hits = sorted(glob.glob(pat)) or [pat]
            reels += [Path(h) for h in hits]
        del args[i:]
    memo = None
    if "--memo" in args:
        i = args.index("--memo")
        memo = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    if len(args) != 2 or args[1] not in ALIASES:
        sys.exit("사용법: submit_status.py <영상 파일|이름 일부> 작업중|편집끝|완료 [--memo 메모] [--reels 파일...]")
    e = find(args[0])
    if not e:
        sys.exit(f"받은 제출에서 찾지 못했습니다: {args[0]}  (--list로 목록 확인)")
    extra = {}
    if reels:
        missing = [str(r) for r in reels if not r.is_file() or r.suffix.lower() != ".mp4"]
        if missing:
            sys.exit(f"릴스 파일이 없거나 mp4가 아닙니다: {missing}")
        dest = finished_dir(e)
        dest.mkdir(parents=True, exist_ok=True)
        for r in reels:
            shutil.copy2(r, dest / r.name)
        n = len(list(dest.glob("*.mp4")))
        extra["reels"] = n
        if memo is None:
            memo = f"릴스 {n}개"
        print(f"완성 폴더: {dest}  (릴스 {n}개)")
    send(e, ALIASES[args[1]], memo, **extra)
    print(f"{e.get('name')} / {e.get('title')} → {LABEL[ALIASES[args[1]]]}")
