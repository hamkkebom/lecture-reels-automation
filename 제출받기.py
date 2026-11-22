#!/usr/bin/env python
"""제출 사이트에 올라온 강의 원본을 내 PC로 받아 오고, 받은 뒤 사이트 쪽 원본을 지운다.

  .venv\\Scripts\\python 제출받기.py            # 한 번 확인하고 끝
  .venv\\Scripts\\python 제출받기.py --watch    # 5분마다 계속 확인 (창을 켜 둔다)
  .venv\\Scripts\\python 제출받기.py --list     # 받지 않고 목록만

설정: 제출받기_설정.json  {"url": "https://...", "token": "ADMIN_TOKEN 값"}
받은 파일: 원본/제출/<학원>/<날짜>_<이름>_<강의 제목>.<확장자>   기록: 원본/제출/받은목록.jsonl
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "제출받기_설정.json").read_text(encoding="utf-8-sig"))
DEST = ROOT / "원본" / "제출"
LOG = DEST / "받은목록.jsonl"
CHUNK = 8 * 1024 * 1024


def call(path: str, method: str = "GET", headers: dict | None = None):
    req = urllib.request.Request(CFG["url"].rstrip("/") + path, method=method,
                                 headers={"authorization": "Bearer " + CFG["token"],
                                          "user-agent": "Mozilla/5.0 (submit-fetcher)",  # Cloudflare가 기본 Python UA를 막음(1010)
                                          **(headers or {})})
    return urllib.request.urlopen(req, timeout=60)


VIDEO_EXT = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm", ".mts", ".m2ts", ".wmv", ".flv", ".3gp"}
MAX_TRIES = 30  # 끊김 재시도 한도 (10초 간격, 약 5분)
FREE_MARGIN = 5 * 2**30  # 받고 나서도 디스크에 남겨 둘 여유


class Skip(Exception):
    """이 제출은 이번에 건너뛰고 다음 것을 받는다."""


def target_name(item: dict) -> Path:
    m = item["meta"]
    day = item["key"].split("/")[1][:10]
    ext = (Path(m.get("filename") or item["key"]).suffix or ".mp4").lower()
    if ext not in VIDEO_EXT:  # 영상이 아닌 확장자(.exe 등)는 실행되지 않게 바꿔 저장
        ext += ".bin"
    base = f"{day}_{m.get('name', '이름없음')}_{m.get('title', '제목없음')}"
    folder = DEST / (m.get("academyName") or "학원없음")  # 학원별 폴더
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / (base + ext)
    n = 2
    while p.exists():
        p = folder / f"{base}_{n}{ext}"
        n += 1
    return p


def download(item: dict) -> Path:
    q = "?key=" + urllib.parse.quote(item["key"], safe="")
    tmp = DEST / (item["key"].split("/")[1] + ".받는중")
    size = item["size"]
    if tmp.exists() and tmp.stat().st_size > size:  # 망가진 임시 파일
        tmp.unlink()
    have = tmp.stat().st_size if tmp.exists() else 0
    if shutil.disk_usage(DEST).free < size - have + FREE_MARGIN:
        raise Skip(f"디스크 공간이 부족합니다 ({size / 2**30:.1f} GB 필요)")
    t0, start, tries = time.time(), have, 0
    while have < size:
        try:
            with call("/api/admin/get" + q, headers={"range": f"bytes={have}-"}) as r, open(tmp, "ab") as f:
                while chunk := r.read(CHUNK):
                    f.write(chunk)
                    have += len(chunk)
                    mb = (have - start) / 2**20
                    print(f"\r  {have / size * 100:5.1f}%  {mb / max(time.time() - t0, 1) * 8:6.0f} Mbps", end="", flush=True)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404, 416):  # 지워졌거나 열쇠가 바뀜: 다시 해도 소용없음
                raise Skip(f"받을 수 없습니다 (HTTP {e.code})")
            tries += 1
            print(f"\n  서버 오류({e.code}), 10초 뒤 다시 ({tries}/{MAX_TRIES})")
            time.sleep(10)
        except Exception as e:  # 끊기면 받은 데까지 두고 이어서
            tries += 1
            print(f"\n  끊김({e}), 10초 뒤 이어 받습니다 ({tries}/{MAX_TRIES})")
            time.sleep(10)
        if tries >= MAX_TRIES:
            raise Skip("계속 끊겨서 다음 확인 때 이어 받습니다")
        have = tmp.stat().st_size if tmp.exists() else 0
    print()
    if tmp.stat().st_size != size:
        tmp.unlink()
        raise Skip("크기가 달라 지웠습니다. 다음 확인 때 다시 받습니다")
    out = target_name(item)
    tmp.rename(out)
    return out


def once(only_list: bool = False) -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    with call("/api/admin/list", headers={"x-client": "pc"}) as r:  # 관리자 페이지에 'PC 켜짐'으로 표시
        items = json.load(r)["items"]
    if not items:
        print(time.strftime("%H:%M"), "새 제출 없음", flush=True)
        return 0
    for it in items:
        m = it["meta"]
        print(f"- {m.get('name')} / {m.get('title')} / {m.get('filename')} / {it['size'] / 2**30:.2f} GB / {it['uploaded']}")
    if only_list:
        return len(items)
    done_keys = set()
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8").splitlines():
            try:
                done_keys.add(json.loads(line).get("key"))
            except ValueError:
                pass
    for it in items:
        m = it["meta"]
        try:
            if it["key"] in done_keys:  # 이미 받았는데 사이트 쪽 삭제만 실패했던 것
                print(f"이미 받음, 사이트 쪽 원본만 지웁니다: {m.get('name')} / {m.get('title')}", flush=True)
            else:
                print(f"받는 중: {m.get('name')} / {m.get('title')}", flush=True)
                out = download(it)
                with open(LOG, "a", encoding="utf-8") as f:  # 지우기 전에 먼저 기록
                    f.write(json.dumps({"file": out.relative_to(DEST).as_posix(), "key": it["key"], "received": time.strftime("%Y-%m-%d %H:%M:%S"), **m}, ensure_ascii=False) + "\n")
                print(f"완료: {out}", flush=True)
            call("/api/admin/delete?reason=received&key=" + urllib.parse.quote(it["key"], safe=""), method="DELETE").close()
            print("  사이트 쪽 원본 삭제함", flush=True)
        except Skip as e:
            print(f"  건너뜀: {e}", flush=True)
        except Exception as e:
            print(f"  실패: {e} (다음 확인 때 다시 시도)", flush=True)
    return len(items)


if __name__ == "__main__":
    if "--list" in sys.argv:
        once(only_list=True)
    elif "--watch" in sys.argv:
        sys.path.insert(0, str(ROOT))
        import deliver  # 관리자 페이지에서 '드라이브로 전달'을 누른 것을 올린다
        import 정리하기  # 전달 7일 지난 원본을 PC에서 지운다
        last_clean = 0.0
        while True:
            try:
                once()
            except Exception as e:
                print("확인 실패:", e, flush=True)
            try:
                deliver.run()
            except Exception as e:
                print("드라이브 전달 확인 실패:", e, flush=True)
            if time.time() - last_clean > 3600:  # 전달 7일 지난 원본 정리 (한 시간에 한 번)
                last_clean = time.time()
                try:
                    정리하기.run()
                except Exception as e:
                    print("PC 정리 실패:", e, flush=True)
            time.sleep(300)
    else:
        once()
