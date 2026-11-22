# 강의 영상 → 인스타 릴스 자동 편집

학원 강의 촬영본을 받아 인스타그램 릴스(9:16, 1080×1920)로 편집하고, 검토 후 학원 구글드라이브로 전달하는 1인 대행 시스템입니다.
여러 학원을 맡고, 정산은 학원별·월별 릴스 개수로 합니다.

```
학원 ──(제출 사이트에 원본 업로드)──▶ Cloudflare R2
                                         │  5분마다
내 PC: 제출받기.py ◀──────────────────────┘  (받은 뒤 사이트 쪽 원본 삭제)
   │
   ├─ 받아쓰기(Whisper) → 구간 고르기 → 자막·제목·그래픽 → 릴스 mp4
   ├─ submit_status.py 편집끝 → 관리자 페이지에 '편집 끝 · 릴스 N개'
   │
사장님 검토 → 관리자 페이지 '드라이브로 전달' → deliver.py가 학원 드라이브에 업로드
                                              → 정산 장부에 자동 기록
```

이 저장소에는 **코드와 설명서만** 있습니다. 강의 영상, 학원 로고·자료, 편집 지시서(강의 대본이 담긴 JSON), 비밀값은 넣지 않았습니다.

## 들어 있는 것

| 부분 | 파일 | 하는 일 |
|---|---|---|
| 제출 사이트 | `제출사이트/` | Cloudflare Workers + R2. 제출 화면(`/`), 관리자 페이지(`/admin`), 학원·정산·텔레그램 알림. 배포 방법은 [`제출사이트/배포하기.md`](제출사이트/배포하기.md) |
| 받아 오기 | `제출받기.py`, `fetcher_*.py/.bat`, `제출받기_설치.bat` | PC가 5분마다 새 제출을 `원본/제출/<학원>/`로 받음. 시작프로그램 등록 |
| 상태·전달 | `submit_status.py`, `deliver.py` | 작업 상태 알림, 구글드라이브 전달(rclone) |
| 정리 | `정리하기.py` | 전달 7일 지난 원본·작업 폴더 삭제 |
| 받아쓰기 | `transcribe_long.py`, `rough.py` | 긴 강의 전체 받아쓰기 → 릴스 구간 후보 찾기 |
| 편집 | `make_reel.py`, `batch_reels.py`, `shortform.py`, `shortform2.py`, `prep43.py` | 무음 컷, 9:16, 단어별 자막, 제목, 요약 카드, 그래픽 |
| 마무리 | `apply_logo_speed.py`, `brand.py`, `make_logo.py` | 학원 로고·색·틀 입히기, 1.2배속(음높이 유지) |
| 확인용 | `style_preview.py`, `make_overview.py`, `samples/` | 틀 비교 이미지, 제작 현황 한 장 정리, 자막 모양 샘플 |
| 기타 | `char_reel.py` | AI 캐릭터 영상에 자막 입히기 |

## 준비물

- Windows + Python 3.10 이상
- FFmpeg 6.1 이상 (PATH에 등록)
- NVIDIA GPU 권장 (받아쓰기 속도)
- Node.js (제출 사이트 배포용 `npx wrangler`)
- rclone (구글드라이브 전달용, 리모트 이름 `gdrive`)
- Cloudflare 계정 (R2를 켜려면 결제 카드 등록 필요, 사용량은 무료 구간 안)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## 처음 설정 순서

1. **제출 사이트 배포**: [`제출사이트/배포하기.md`](제출사이트/배포하기.md)를 따라 R2 버킷을 만들고 `SUBMIT_CODE`, `ADMIN_TOKEN`, `ADMIN_PASSWORD`를 `wrangler secret put`으로 넣은 뒤 배포합니다.
2. **PC 연결**: `제출받기_설정.예시.json`을 `제출받기_설정.json`으로 복사하고 주소와 `ADMIN_TOKEN`을 넣습니다. 이 파일은 절대 공유하지 않습니다.
3. **설치**: `제출받기_설치.bat`을 더블클릭하면 연결을 확인하고 시작프로그램과 바탕화면 아이콘(제출 받기 켜기, 제출 관리)을 만듭니다.
4. **학원 등록**: 관리자 페이지 '학원'에서 이름, 전용 제출 코드, 틀, 색 3가지, 드라이브 폴더, 로고(투명 PNG)를 넣습니다. 드라이브 폴더는 내 구글 계정에 '편집자'로 공유되어 있어야 합니다.
5. **(선택) 텔레그램 알림**: BotFather로 봇을 만들고, 봇에게 '시작'을 누른 뒤, 관리자 페이지 '텔레그램 알림' 칸에 토큰을 넣습니다.

## 편집 흐름 한 번

```powershell
# 1) 긴 강의를 받아써서 릴스 구간 후보 찾기
.venv\Scripts\python transcribe_long.py 원본\제출\<학원>\<파일>.mp4

# 2) 구간을 정해 릴스_설정.json(또는 그래픽_*.json 지시서)에 적고 준비
.venv\Scripts\python batch_reels.py prep

# 3) 자막 교정 후 내보내기, 로고·배속 마무리
.venv\Scripts\python batch_reels.py render
.venv\Scripts\python apply_logo_speed.py 그래픽_<이름>.json

# 4) 관리자 페이지에 '편집 끝' 알리기 (릴스가 완성\<학원>\<제출 이름>\ 에 모임)
.venv\Scripts\python submit_status.py <이름 일부> 편집끝 --reels output\a.mp4 output\b.mp4
```

지시서 JSON에 `"academy": "학원 이름"`을 적으면 그 학원의 틀·색·로고로 만듭니다.

## 편집 원칙 (실제로 해 보며 정한 것)

- 말을 중간에 자르지 않는다. 구간 시작·끝은 문장 단위로.
- 화면을 덮는 그래픽은 강사가 화면 밖에 있을 때만 쓴다.
- 자막은 기계적으로 자르지 않고 의미 단위로 직접 나눈다.
- 전체 1.2배속(음높이 유지).
- 아래 띠에 요약 카드가 없을 때는 학원 로고를 띄운다.

## 보안·개인정보

- 비밀값(`SUBMIT_CODE`, `ADMIN_TOKEN`, `ADMIN_PASSWORD`, 텔레그램 봇 토큰)은 코드에 적지 않고 Cloudflare secret이나 R2에만 둡니다.
- 제출 화면에서 '강사 촬영·편집·홍보 이용 동의' 체크가 있어야 업로드됩니다. 실제 동의는 학원과의 계약서에도 넣어 두는 것이 안전합니다.
- 원본은 3단계로 지웁니다: PC가 받으면 사이트에서 바로 삭제 → R2 3일 자동 만료 → PC에서 전달 7일 후 삭제.

## 참고

- 코드의 기본 학원 이름(`brand.py`의 `DEFAULT_ACADEMY`)은 처음 작업한 학원입니다. 자기 학원 이름으로 바꿔 쓰세요.
- 이 프로젝트는 Claude Code로 만들었습니다.
