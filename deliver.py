#!/usr/bin/env python
"""관리자 페이지에서 '드라이브로 전달'을 누른 제출을 학원 구글드라이브 폴더로 올린다.

제출받기.py --watch 가 5분마다 함께 부른다. 따로 돌릴 때:
  .venv\\Scripts\\python deliver.py            # 전달 요청된 것을 지금 올린다
  .venv\\Scripts\\python deliver.py --check    # 드라이브 연결만 확인

올리는 것: 완성/<학원>/<제출 이름>/*.mp4  →  학원 드라이브 폴더/<제출 이름>/
구글드라이브 연결은 rclone 을 쓴다 (리모트 이름 gdrive, 처음 한 번 사장님이 구글 로그인).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import submit_status as ss

ROOT = Path(__file__).resolve().parent
REMOTE = "gdrive"
# 스토어판 Python은 AppData\Roaming 을 가상화해서 rclone 기본 설정을 못 본다 → 홈 폴더 설정을 명시
CONF = Path.home() / ".config" / "rclone" / "rclone.conf"


def rclone() -> str | None:
    exe = shutil.which("rclone")
    if not exe:
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        hits = sorted(base.glob("Rclone.Rclone*/rclone-*/rclone.exe"))
        exe = str(hits[-1]) if hits else None
    return exe


def rc(exe: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([exe, "--config", str(CONF), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def folder_id(drive: str) -> str | None:
    """드라이브 폴더 주소(또는 ID)에서 폴더 ID를 뽑는다."""
    drive = (drive or "").strip()
    m = re.search(r"/folders/([A-Za-z0-9_-]{10,})", drive) or re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", drive)
    if m:
        return m.group(1)
    return drive if re.fullmatch(r"[A-Za-z0-9_-]{10,}", drive) else None


def api(path: str, body: dict | None = None):
    cfg = json.loads((ROOT / "제출받기_설정.json").read_text(encoding="utf-8-sig"))
    req = urllib.request.Request(cfg["url"].rstrip("/") + path, data=json.dumps(body).encode() if body else None,
                                 method="POST" if body else "GET",
                                 headers={"authorization": "Bearer " + cfg["token"], "content-type": "application/json",
                                          "user-agent": "Mozilla/5.0 (submit-fetcher)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fail(entry_or_id, why: str) -> None:
    rid = entry_or_id if isinstance(entry_or_id, str) else entry_or_id["key"].split("/")[1]
    print(f"  전달 실패: {why}", flush=True)
    api("/api/admin/status", {"id": rid, "status": "ready", "memo": ("전달 실패: " + why)[:100]})


def connected(exe: str) -> bool:
    r = rc(exe, "listremotes")
    return f"{REMOTE}:" in r.stdout.split()


def run() -> int:
    data = api("/api/admin/records")
    todo = [i for i in data["items"] if i.get("status") == "delivering"]
    if not todo:
        return 0
    acads = {a["id"]: a for a in data.get("academies", [])}
    exe = rclone()
    by_key = {e["key"]: e for e in ss.received()}
    for it in todo:
        print(f"드라이브 전달: {it.get('academyName')} / {it.get('name')} / {it.get('title')}", flush=True)
        if not exe or not connected(exe):
            fail(it["id"], "이 PC에 구글드라이브가 연결되어 있지 않습니다 (deliver.py --check)")
            continue
        entry = by_key.get(it.get("key"))
        if not entry:
            fail(it["id"], "이 PC에서 받은 기록이 없습니다")
            continue
        src = ss.finished_dir(entry)
        reels = sorted(src.glob("*.mp4")) if src.is_dir() else []
        if not reels:
            fail(entry, f"완성 폴더에 릴스가 없습니다 ({src.relative_to(ROOT)})")
            continue
        acad = acads.get(it.get("academy"))
        fid = folder_id(acad.get("drive", "")) if acad else None
        if not fid:
            fail(entry, "학원 설정에 드라이브 폴더 주소가 없거나 잘못되었습니다")
            continue
        r = rc(exe, "copy", str(src), f"{REMOTE}:{src.name}", "--drive-root-folder-id", fid,
               "--include", "*.mp4", "--transfers", "2", "--retries", "5", "--stats", "0")
        if r.returncode:
            err = (r.stderr.strip().splitlines() or ["알 수 없는 오류"])[-1]
            fail(entry, "드라이브 올리기 오류: " + err[-70:])
            continue
        api("/api/admin/status", {"id": it["id"], "status": "done", "delivered": True, "reels": len(reels),
                                  "memo": f"드라이브 전달 {len(reels)}개"})
        print(f"  완료: 릴스 {len(reels)}개 → {acad['name']} 드라이브/{src.name}", flush=True)
    return len(todo)


def check() -> None:
    exe = rclone()
    if not exe:
        sys.exit("rclone 이 설치되어 있지 않습니다.")
    if not connected(exe):
        sys.exit(f"rclone 에 '{REMOTE}' 연결이 없습니다. 구글 로그인으로 연결해야 합니다.")
    r = rc(exe, "about", f"{REMOTE}:", "--json")
    print("드라이브 연결: 정상" if r.returncode == 0 else f"드라이브 연결 오류: {r.stderr.strip()[-200:]}")


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    else:
        print(f"전달 요청 {run()}건 처리")
