"""이 PC에 제출 받기를 설치한다 (작업 컴퓨터를 바꿨을 때 새 PC에서 한 번 실행).

- 컴퓨터를 켜면 제출 받기가 저절로 켜지게 (시작프로그램, 창은 작업 표시줄에 최소화)
- 바탕화면에 '제출 받기 켜기', '제출 관리' 아이콘
- 제출받기_설정.json이 있는지, 사이트에 연결되는지 확인
"""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

here = Path(__file__).resolve().parent
bat = here / "fetcher_watch.bat"
cfg_path = here / "제출받기_설정.json"

print("== 제출 받기 설치 ==\n")
if not cfg_path.exists():
    sys.exit("제출받기_설정.json이 없습니다. 예전 PC의 프로젝트 폴더에서 이 파일도 함께 복사해 주세요.")
cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))

try:
    req = urllib.request.Request(cfg["url"].rstrip("/") + "/api/admin/list",
                                 headers={"authorization": "Bearer " + cfg["token"], "user-agent": "Mozilla/5.0 (submit-fetcher)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        n = len(json.load(r)["items"])
    print(f"사이트 연결: 정상 (지금 받을 제출 {n}건)")
except Exception as e:
    sys.exit(f"사이트에 연결하지 못했습니다: {e}")

# 바로가기 만들기 (PowerShell COM). 한글 경로는 환경 변수로 넘긴다.
ps = r"""
$ws = New-Object -ComObject WScript.Shell
$desk = [Environment]::GetFolderPath('Desktop'); $st = [Environment]::GetFolderPath('Startup')
foreach ($d in @($desk, $st)) {
  $l = $ws.CreateShortcut((Join-Path $d '제출 받기 켜기.lnk'))
  $l.TargetPath = $env:FETCH_BAT; $l.WorkingDirectory = $env:FETCH_DIR
  if ($d -eq $st) { $l.WindowStyle = 7 }
  $l.Save()
}
Set-Content -Path (Join-Path $desk '제출 관리.url') -Value ("[InternetShortcut]`r`nURL=" + $env:ADMIN_URL) -Encoding ascii
Write-Output $st
"""
env = {**os.environ, "FETCH_BAT": str(bat), "FETCH_DIR": str(here), "ADMIN_URL": cfg["url"].rstrip("/") + "/admin"}
r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                   env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
if r.returncode != 0:
    sys.exit("바로가기를 만들지 못했습니다:\n" + r.stderr)
print("시작프로그램 등록: 완료 (컴퓨터를 켜면 저절로 켜집니다)")
print("바탕화면 아이콘: '제출 받기 켜기', '제출 관리'")
print("\n주의: 예전 PC에서도 제출 받기가 켜져 있으면 두 PC가 나눠 받게 됩니다.")
print("예전 PC에서는 시작프로그램의 '제출 받기 켜기'를 지워 주세요 (Win+R → shell:startup).")
