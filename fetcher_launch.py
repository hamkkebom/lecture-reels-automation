"""fetcher_watch.bat에서 부른다: 창 제목을 달고 제출받기.py --watch를 실행한다."""
import os
import runpy
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
os.system("title 제출 받기 - 이 창을 켜 두세요")
print("새 제출을 5분마다 확인해서 원본\\제출 폴더로 받아 옵니다.")
print("그만하려면 이 창을 닫으세요.\n", flush=True)
sys.argv = [str(here / "제출받기.py"), "--watch"]
runpy.run_path(str(here / "제출받기.py"), run_name="__main__")
