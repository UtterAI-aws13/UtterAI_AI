#!/usr/bin/env python3
"""ASR 후처리 전후 성능 비교 스크립트.

실제 Whisper가 자주 뱉는 문제 유형(None timestamp, 겹침, 환각 중복, 빈 텍스트 등)을
픽스처로 정의하고, 구 버전과 신 버전 후처리 로직을 같은 입력으로 측정한다.

사용법:
    # 1단계: 현재 코드(수정 후) 측정 및 저장
    python scripts/benchmark_asr_postprocess.py --save new

    # 2단계: 구 코드로 전환 후 측정 및 저장
    git stash
    python scripts/benchmark_asr_postprocess.py --save old

    # 3단계: 코드 복원 후 비교표 출력
    git stash pop
    python scripts/benchmark_asr_postprocess.py --compare
"""

import argparse
import json
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (app 패키지 임포트)
sys.path.insert(0, str(Path(__file__).parent.parent))

# 결과 저장 경로
RESULTS_DIR = Path("scripts/.benchmark_results")
RESULTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# 픽스처 정의 — 실제 Whisper가 자주 뱉는 문제 유형
# ---------------------------------------------------------------------------

FIXTURES = [
    {
        "name": "정상 입력",
        "desc": "문제 없는 깔끔한 세그먼트 5개",
        "audio_duration": 30.0,
        "expected_segments": 5,
        "expected_coverage_min": 95.0,
        "chunks": [
            {"timestamp": (0.0, 5.0),  "text": "안녕하세요"},
            {"timestamp": (5.0, 10.0), "text": "오늘 날씨가"},
            {"timestamp": (10.0, 18.0),"text": "정말 좋네요"},
            {"timestamp": (18.0, 24.0),"text": "같이 산책할까요"},
            {"timestamp": (24.0, 30.0),"text": "좋아요 가요"},
        ],
    },
    {
        "name": "None end timestamp",
        "desc": "마지막 세그먼트 end가 None (Whisper 빈번 발생)",
        "audio_duration": 20.0,
        "expected_segments": 3,
        "expected_coverage_min": 90.0,
        "chunks": [
            {"timestamp": (0.0, 6.0),  "text": "첫번째"},
            {"timestamp": (6.0, 12.0), "text": "두번째"},
            {"timestamp": (12.0, None),"text": "세번째"},  # None end
        ],
    },
    {
        "name": "중간 None end timestamp",
        "desc": "중간 세그먼트 end가 None",
        "audio_duration": 15.0,
        "expected_segments": 3,
        "expected_coverage_min": 85.0,
        "chunks": [
            {"timestamp": (0.0, 4.0),  "text": "처음"},
            {"timestamp": (4.0, None), "text": "중간"},      # None end
            {"timestamp": (9.0, 15.0), "text": "끝"},
        ],
    },
    {
        "name": "60초 오디오 3청크 (핵심 버그 시나리오)",
        "desc": "chunk=30 stride=5 step=20 → 60s 오디오 3청크, 40초 이후 발화 포함",
        "audio_duration": 60.0,
        "expected_segments": 6,
        "expected_coverage_min": 90.0,
        "chunks": [
            {"timestamp": (0.0, 8.0),  "text": "첫번째 발화"},
            {"timestamp": (8.0, 16.0), "text": "두번째 발화"},
            {"timestamp": (16.0, 25.0),"text": "세번째 발화"},
            {"timestamp": (25.0, 37.0),"text": "네번째 발화"},
            {"timestamp": (37.0, 50.0),"text": "다섯번째 발화"},
            {"timestamp": (50.0, 60.0),"text": "여섯번째 발화 (40초 이후)"},
        ],
    },
    {
        "name": "청크 경계 겹침",
        "desc": "stride 처리 아티팩트: 두 청크가 같은 구간을 중복 출력",
        "audio_duration": 50.0,
        "expected_segments": 3,   # 겹치는 세그먼트를 제거하면 3개가 올바른 결과
        "expected_coverage_min": 80.0,
        "chunks": [
            {"timestamp": (0.0, 12.0), "text": "앞부분"},
            {"timestamp": (12.0, 25.0),"text": "청크1 끝"},
            {"timestamp": (20.0, 35.0),"text": "겹침 구간"},   # 20~25 겹침 → 제거 대상
            {"timestamp": (35.0, 50.0),"text": "뒷부분"},
        ],
    },
    {
        "name": "Whisper 환각 중복 루프",
        "desc": "같은 텍스트를 연속 반복 (환각)",
        "audio_duration": 30.0,
        "expected_segments": 3,
        "expected_coverage_min": 65.0,  # 중복 제거 후 커버리지 ~66.7%
        "chunks": [
            {"timestamp": (0.0, 5.0),  "text": "정상 발화"},
            {"timestamp": (5.0, 10.0), "text": "환각 반복"},
            {"timestamp": (10.0, 15.0),"text": "환각 반복"},   # 중복
            {"timestamp": (15.0, 20.0),"text": "환각 반복"},   # 중복
            {"timestamp": (20.0, 30.0),"text": "다시 정상"},
        ],
    },
    {
        "name": "빈 텍스트 세그먼트",
        "desc": "Whisper가 침묵 구간에 빈 텍스트 세그먼트를 생성",
        "audio_duration": 25.0,
        "expected_segments": 3,
        "expected_coverage_min": 60.0,
        "chunks": [
            {"timestamp": (0.0, 5.0),  "text": "말하는 구간"},
            {"timestamp": (5.0, 10.0), "text": "   "},          # 공백
            {"timestamp": (10.0, 15.0),"text": ""},             # 빈 문자열
            {"timestamp": (15.0, 20.0),"text": "다시 말함"},
            {"timestamp": (20.0, 25.0),"text": "마무리"},
        ],
    },
    {
        "name": "역방향 timestamp",
        "desc": "end < start (Whisper 엣지케이스)",
        "audio_duration": 20.0,
        "expected_segments": 3,
        "expected_coverage_min": 65.0,  # 역방향 세그먼트 보정 후 커버리지 ~67.5%
        "chunks": [
            {"timestamp": (0.0, 5.0),  "text": "정상1"},
            {"timestamp": (8.0, 7.0),  "text": "역방향"},       # end < start
            {"timestamp": (12.0, 20.0),"text": "정상2"},
        ],
    },
    {
        "name": "복합 문제",
        "desc": "None end + 겹침 + 빈 텍스트 + 환각이 동시에 발생",
        "audio_duration": 45.0,
        "expected_segments": 5,   # 빈텍스트 1개 제거, 환각중복 1개 제거 → 5개
        "expected_coverage_min": 75.0,
        "chunks": [
            {"timestamp": (0.0, 8.0),   "text": "정상 발화"},
            {"timestamp": (8.0, None),  "text": "None end"},    # None end
            {"timestamp": (13.0, 20.0), "text": ""},            # 빈 텍스트
            {"timestamp": (15.0, 25.0), "text": "겹침 발화"},   # 겹침
            {"timestamp": (25.0, 30.0), "text": "반복 환각"},
            {"timestamp": (30.0, 35.0), "text": "반복 환각"},   # 중복
            {"timestamp": (35.0, 45.0), "text": "마지막 발화"},
        ],
    },
]


# ---------------------------------------------------------------------------
# 구 버전 후처리 로직 (수정 전 코드 그대로 복사)
# ---------------------------------------------------------------------------

def old_postprocess(chunks: list[dict], audio_duration: float) -> list[dict]:
    """수정 전 predict() 내부 인라인 후처리. 정렬/필터/중복제거 없음."""
    from app.schemas import ASRSegment

    segments = []
    for i, chunk in enumerate(chunks):
        ts = chunk.get("timestamp") or (None, None)
        text = chunk.get("text", "").strip()
        start = float(ts[0]) if ts[0] is not None else 0.0
        end = float(ts[1]) if ts[1] is not None else start + 1.0  # 구 버전 fallback
        segments.append(
            ASRSegment(
                asr_segment_id=f"asr_{i:03d}",
                start_time=round(start, 3),
                end_time=round(end, 3),
                text=text,
                confidence=1.0,
            )
        )
    return segments


# ---------------------------------------------------------------------------
# 신 버전 후처리 로직 (WhisperASRWrapper._postprocess_chunks)
# ---------------------------------------------------------------------------

def new_postprocess(chunks: list[dict], audio_duration: float) -> list[dict]:
    """수정 후 _postprocess_chunks() 호출."""
    from app.models.asr_whisper import WhisperASRWrapper

    wrapper = WhisperASRWrapper(model_name="dummy")
    return wrapper._postprocess_chunks(chunks, audio_duration)


# ---------------------------------------------------------------------------
# 지표 계산
# ---------------------------------------------------------------------------

def compute_metrics(segments: list, audio_duration: float, fixture: dict) -> dict:
    """세그먼트 목록에서 품질 지표를 계산한다."""
    n = len(segments)

    # 커버리지: 중복 제거 후 실제 커버된 시간 / 전체 오디오 길이
    events = [(seg.start_time, seg.end_time) for seg in segments]
    events.sort()
    covered = 0.0
    cursor = 0.0
    for s, e in events:
        if s > cursor:
            covered += e - s
            cursor = e
        elif e > cursor:
            covered += e - cursor
            cursor = e
    coverage_pct = round(covered / audio_duration * 100, 1) if audio_duration > 0 else 0.0

    # 유효하지 않은 timestamp (end <= start)
    n_invalid_ts = sum(
        1 for seg in segments if seg.end_time <= seg.start_time
    )

    # 빈 텍스트 세그먼트
    n_empty = sum(1 for seg in segments if not seg.text.strip())

    # 연속 중복 텍스트
    texts = [seg.text for seg in segments]
    n_dup = sum(1 for a, b in zip(texts, texts[1:]) if a == b)

    # 겹침 세그먼트 수
    n_overlap = 0
    cursor2 = 0.0
    for seg in segments:
        if seg.start_time < cursor2:
            n_overlap += 1
        cursor2 = max(cursor2, seg.end_time)

    # 기대 세그먼트 수와 일치 여부
    expected_n = fixture["expected_segments"]
    expected_cov = fixture["expected_coverage_min"]
    seg_count_ok = (n == expected_n)
    coverage_ok = (coverage_pct >= expected_cov)

    # 오류 항목 합계
    total_errors = n_invalid_ts + n_empty + n_dup + n_overlap

    return {
        "n_segments": n,
        "expected_segments": expected_n,
        "seg_count_ok": seg_count_ok,
        "coverage_pct": coverage_pct,
        "expected_coverage_min": expected_cov,
        "coverage_ok": coverage_ok,
        "n_invalid_ts": n_invalid_ts,
        "n_empty_text": n_empty,
        "n_consecutive_dup": n_dup,
        "n_overlap": n_overlap,
        "total_errors": total_errors,
        "pass": seg_count_ok and coverage_ok and total_errors == 0,
    }


# ---------------------------------------------------------------------------
# 벤치마크 실행
# ---------------------------------------------------------------------------

def run_benchmark(postprocess_fn) -> list[dict]:
    results = []
    for fixture in FIXTURES:
        segs = postprocess_fn(fixture["chunks"], fixture["audio_duration"])
        metrics = compute_metrics(segs, fixture["audio_duration"], fixture)
        results.append({
            "name": fixture["name"],
            "desc": fixture["desc"],
            **metrics,
        })
    return results


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------

def print_results_table(label: str, results: list[dict]) -> None:
    PASS = "✓"
    FAIL = "✗"

    print(f"\n{'='*72}")
    print(f"  {label}")
    print(f"{'='*72}")
    header = f"{'시나리오':<26} {'세그먼트':>6} {'커버리지':>8} {'오류수':>6} {'결과':>4}"
    print(header)
    print("-" * 72)
    for r in results:
        mark = PASS if r["pass"] else FAIL
        seg_info = f"{r['n_segments']}/{r['expected_segments']}"
        cov_info = f"{r['coverage_pct']}%"
        print(
            f"{r['name']:<26} {seg_info:>6} {cov_info:>8} "
            f"{r['total_errors']:>6}   {mark}"
        )
    print("-" * 72)
    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    avg_cov = round(sum(r["coverage_pct"] for r in results) / total, 1)
    total_err = sum(r["total_errors"] for r in results)
    print(f"{'합계':<26} {'':>6} {f'{avg_cov}%':>8} {total_err:>6}   {passed}/{total} 통과")


def print_comparison_table(old_results: list[dict], new_results: list[dict]) -> None:
    print(f"\n{'='*88}")
    print("  전후 비교")
    print(f"{'='*88}")
    header = (
        f"{'시나리오':<26} "
        f"{'Before 세그/커버/오류':>20} "
        f"{'After 세그/커버/오류':>20} "
        f"{'개선':>8}"
    )
    print(header)
    print("-" * 88)

    for o, n in zip(old_results, new_results):
        assert o["name"] == n["name"]
        o_summary = f"{o['n_segments']}/{o['expected_segments']} {o['coverage_pct']}% err={o['total_errors']}"
        n_summary = f"{n['n_segments']}/{n['expected_segments']} {n['coverage_pct']}% err={n['total_errors']}"
        improved = ""
        if not o["pass"] and n["pass"]:
            improved = "✓ FIXED"
        elif o["pass"] and n["pass"]:
            improved = "유지"
        elif o["pass"] and not n["pass"]:
            improved = "✗ 퇴보"
        else:
            err_diff = o["total_errors"] - n["total_errors"]
            cov_diff = round(n["coverage_pct"] - o["coverage_pct"], 1)
            if err_diff > 0 or cov_diff > 0:
                improved = f"부분개선 err-{err_diff}"
            else:
                improved = "미변화"
        print(f"{o['name']:<26} {o_summary:>20} {n_summary:>20} {improved:>8}")

    print("-" * 88)
    o_passed = sum(1 for r in old_results if r["pass"])
    n_passed = sum(1 for r in new_results if r["pass"])
    o_avg_cov = round(sum(r["coverage_pct"] for r in old_results) / len(old_results), 1)
    n_avg_cov = round(sum(r["coverage_pct"] for r in new_results) / len(new_results), 1)
    o_total_err = sum(r["total_errors"] for r in old_results)
    n_total_err = sum(r["total_errors"] for r in new_results)
    total = len(old_results)

    print(f"\n  통과:     {o_passed}/{total}  →  {n_passed}/{total}  "
          f"(+{n_passed - o_passed})")
    print(f"  평균커버리지: {o_avg_cov}%  →  {n_avg_cov}%  "
          f"({'+' if n_avg_cov >= o_avg_cov else ''}{round(n_avg_cov - o_avg_cov, 1)}%p)")
    print(f"  총 오류:   {o_total_err}건  →  {n_total_err}건  "
          f"(-{o_total_err - n_total_err}건)\n")


# ---------------------------------------------------------------------------
# CLI 진입점
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="ASR 후처리 전후 성능 비교")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--save",
        choices=["old", "new"],
        help="현재 코드로 벤치마크 실행 후 결과 저장 (old 또는 new)",
    )
    group.add_argument(
        "--compare",
        action="store_true",
        help="저장된 old/new 결과를 불러와 비교표 출력",
    )
    args = parser.parse_args()

    if args.compare:
        old_path = RESULTS_DIR / "old.json"
        new_path = RESULTS_DIR / "new.json"
        if not old_path.exists() or not new_path.exists():
            print("오류: old.json 또는 new.json 이 없습니다.")
            print("먼저 --save old, --save new 로 각각 저장하세요.")
            sys.exit(1)
        old_results = json.loads(old_path.read_text())
        new_results = json.loads(new_path.read_text())
        print_results_table("Before (수정 전)", old_results)
        print_results_table("After  (수정 후)", new_results)
        print_comparison_table(old_results, new_results)
        return

    # --save 또는 기본 실행
    if args.save == "old":
        postprocess_fn = old_postprocess
        label = "Before (수정 전 — 구 버전 인라인 로직)"
    else:
        # 신 버전 import 가능 여부 확인
        try:
            from app.models.asr_whisper import WhisperASRWrapper
            _ = WhisperASRWrapper._postprocess_chunks
            postprocess_fn = new_postprocess
            label = "After  (수정 후 — _postprocess_chunks)"
        except (ImportError, AttributeError):
            print("경고: 신 버전 코드(_postprocess_chunks)를 찾을 수 없습니다.")
            print("git stash 상태에서 --save new를 실행한 것 같습니다.")
            print("대신 구 버전 로직으로 측정합니다. (--save old 로 다시 실행하세요)")
            postprocess_fn = old_postprocess
            label = "Before (수정 전 — 구 버전 인라인 로직)"

    results = run_benchmark(postprocess_fn)
    print_results_table(label, results)

    if args.save:
        save_path = RESULTS_DIR / f"{args.save}.json"
        save_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"\n결과 저장: {save_path}")
        if args.save == "new":
            print("다음 단계: git stash → python scripts/benchmark_asr_postprocess.py --save old")
        elif args.save == "old":
            print("다음 단계: git stash pop → python scripts/benchmark_asr_postprocess.py --compare")


if __name__ == "__main__":
    main()
