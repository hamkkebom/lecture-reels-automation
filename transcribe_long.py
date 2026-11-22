#!/usr/bin/env python
"""긴 수업 영상 전체를 빠르게 받아써서 '릴스 구간 찾기용' 대본을 만든다.

속도를 위해: 소리만 먼저 뽑고(16kHz 모노), GPU 배치 처리, 단어 단위 시각은 끔.
자막용 정밀 받아쓰기는 고른 클립에만 make_reel.py 가 따로 한다.

실행 (프로젝트 폴더에서):
  .venv\\Scripts\\python transcribe_long.py 수업.mp4 --hint "고1 내신 문법, 동명사, to부정사"
  .venv\\Scripts\\python transcribe_long.py 수업.mp4 --limit-minutes 10     # 속도만 먼저 재보기

결과: work/<이름>/transcript.txt (시각 + 문장), transcript.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from make_reel import ROOT, add_cuda_dlls, load_audio_16k


def hms(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", type=Path, help="긴 원본 영상 또는 음성 파일")
    p.add_argument("--hint", default="", help="수업 주제·용어. 받아쓰기 용어 인식에 쓰임")
    p.add_argument("--model", default="large-v3-turbo")
    p.add_argument("--language", default="ko")
    p.add_argument("--batch-size", type=int, default=12, help="GPU에 한 번에 넣는 조각 수 (8GB면 8~16)")
    p.add_argument("--limit-minutes", type=float, help="앞부분 N분만 받아써서 속도를 잰다")
    p.add_argument("--words", action="store_true",
                   help="단어별 시각도 저장한다 (transcript_words.json). 구간의 정확한 시작·끝을 고를 때 쓴다")
    p.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    a = p.parse_args()

    src = a.input.resolve()
    if not src.is_file():
        raise SystemExit(f"원본을 찾을 수 없음: {src}")
    work = ROOT / "work" / src.stem
    work.mkdir(parents=True, exist_ok=True)
    if not a.limit_minutes:  # 제출로 받은 영상이면 관리자 페이지에 '작업 중' 표시
        from submit_status import mark
        mark(src, "working")

    t0 = time.time()
    audio = load_audio_16k(src, work)
    if a.limit_minutes:
        audio = audio[: int(a.limit_minutes * 60 * 16000)]
    total = len(audio) / 16000
    t_extract = time.time() - t0
    print(f"소리 추출 {t_extract:.0f}초, 받아쓸 길이 {hms(total)}", flush=True)

    add_cuda_dlls()
    from faster_whisper import BatchedInferencePipeline, WhisperModel

    attempts = [("cuda", "float16"), ("cpu", "int8")] if a.device == "auto" else [
        (a.device, "float16" if a.device == "cuda" else "int8")]
    segs: list[dict] = []
    last_err: Exception | None = None
    for dev, ctype in attempts:
        try:
            print(f"[whisper] {a.model} / {dev} / {ctype} / batch {a.batch_size}", flush=True)
            t1 = time.time()
            pipe = BatchedInferencePipeline(WhisperModel(a.model, device=dev, compute_type=ctype))
            it, _info = pipe.transcribe(audio, language=a.language, batch_size=a.batch_size,
                                        word_timestamps=a.words, without_timestamps=False,
                                        initial_prompt=a.hint or None)
            segs, words = [], []
            nxt = 600.0
            for s in it:
                text = s.text.strip()
                if text:
                    segs.append({"start": round(float(s.start), 2), "end": round(float(s.end), 2), "text": text})
                for w in (s.words or []) if a.words else []:
                    if w.word.strip():
                        words.append({"start": round(float(w.start), 2), "end": round(float(w.end), 2),
                                      "text": w.word.strip()})
                if s.end >= nxt:
                    print(f"  ... {hms(s.end)} / {hms(total)}", flush=True)
                    nxt += 600.0
            t_asr = time.time() - t1
            break
        except Exception as e:  # GPU 문제면 CPU로 한 번 더
            last_err = e
            print(f"[whisper] {dev} 실패: {e}", flush=True)
    else:
        raise SystemExit(f"음성 인식 실패: {last_err}")

    segs.sort(key=lambda s: s["start"])
    (work / "transcript.json").write_text(json.dumps(segs, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.words:
        words.sort(key=lambda w: w["start"])
        (work / "transcript_words.json").write_text(json.dumps(words, ensure_ascii=False, indent=1),
                                                    encoding="utf-8")
        print(f"단어 {len(words)}개 -> transcript_words.json")
    txt = work / "transcript.txt"
    txt.write_text("\n".join(f"[{hms(s['start'])}-{hms(s['end'])}] {s['text']}" for s in segs) + "\n",
                   encoding="utf-8")

    speed = total / t_asr if t_asr else 0
    print(f"\n받아쓰기 {t_asr:.0f}초 (실시간의 {speed:.0f}배), 문장 {len(segs)}개 -> {txt}")
    if a.limit_minutes:
        print(f"이 속도면 2시간 30분 분량은 약 {9000 / speed / 60:.1f}분 걸립니다 (모델 불러오는 시간 포함 추정).")


if __name__ == "__main__":
    main()
