# ASR 전사문 품질 개선: 원인 분석 및 검증 결과

## 개요

60초 이상 오디오의 전사문이 ~40초에서 잘리는 버그와, Whisper 출력에서 자주 발생하는
후처리 품질 문제(None timestamp, 겹침, 환각 중복 등)를 수정한 내역과 검증 결과를 기록한다.

---

## 버그 원인 분석

### 1. 핵심 버그: `batch_size=8` + transformers 4.47.1

| 항목 | 값 |
|------|-----|
| 영향 범위 | 오디오 길이 > ~50초인 모든 파일 |
| 증상 | 전사문이 ~40초에서 잘림, 이후 발화 누락 |
| 원인 | transformers 4.47.1에서 `batch_size > 1`로 3청크 이상 처리 시 타임스탬프 오프셋 오계산 |

**청킹 계산** (`chunk_length_s=30`, `stride_length_s=5`)

```
step = chunk_length - stride_left - stride_right = 30 - 5 - 5 = 20초

오디오 48초 (청크 2개) → 정상
  Chunk 0: [0-30s]  → 유효 [0-25s]
  Chunk 1: [20-48s] → 유효 [25-48s]

오디오 60초 (청크 3개) → 40초에서 잘림
  Chunk 0: [0-30s]  → 유효 [0-25s]
  Chunk 1: [20-50s] → 유효 [25-45s]  ← 이 청크의 오프셋이 잘못 계산됨
  Chunk 2: [40-60s] → 유효 [45-60s]  ← 결과에서 누락
```

`batch_size=8`로 3개의 청크가 한 배치에 묶일 때, transformers 4.47.1의
배치 내 청크별 stride 메타데이터 인덱싱 버그로 2번째 청크 이후 타임스탬프가 틀어짐.

**수정:** `asr_batch_size: int = 8` → `asr_batch_size: int = 1`

---

### 2. 추가 후처리 품질 문제 (수정 전 코드의 `predict()` 인라인 로직)

| 문제 | 구 코드 동작 | 신 코드 동작 |
|------|-------------|-------------|
| `end=None` timestamp | `start + 1.0`으로 고정 → 오디오 커버리지 손실 | 다음 세그먼트 시작시간 또는 오디오 전체 길이로 정확히 수정 |
| `end <= start` | 그대로 통과 → alignment 오류 유발 | `start + 0.5`로 보정 |
| 빈 텍스트 세그먼트 | 포함 → 불필요한 segment ID 소비 | 필터링 |
| 청크 경계 겹침 | 포함 → 중복 발화 alignment 오류 | forward sweep으로 제거 |
| Whisper 환각 중복 | 포함 → 같은 텍스트가 여러 번 alignment됨 | 연속 중복 텍스트 제거 |
| 시간 정렬 | 입력 순서 그대로 | 시작 시간 기준 정렬 |

---

## 변경 파일

```
app/models/asr_whisper.py   — batch_size 기본값 변경, _postprocess_chunks 신설
app/config.py               — asr_batch_size: 8 → 1 (버그 주석 포함)
tests/unit/test_asr_postprocess.py  — 후처리 단위 테스트 16개 추가
scripts/benchmark_asr_postprocess.py — 전후 성능 비교 스크립트
```

---

## 테스트 방법

### 단위 테스트 (GPU 불필요)

후처리 로직(`_postprocess_chunks`)만 독립적으로 검증한다.
모델 로드 없이 실행 가능하다.

```bash
# 프로젝트 루트에서 실행
python -m pytest tests/unit/test_asr_postprocess.py -v
```

**테스트 항목 (16개)**

| 클래스 | 테스트 |
|--------|--------|
| `TestEmptyTextFilter` | 빈 텍스트 제거, 전부 빈 경우 |
| `TestTimestampFix` | None end → 다음 시작, None end 마지막 → 오디오 길이, end=start 보정, end<start 보정 |
| `TestSorting` | 순서 뒤바뀐 청크 정렬 |
| `TestOverlapRemoval` | 겹침 세그먼트 건너뜀, 비겹침 유지, ID 재번호부여 |
| `TestHallucinationFilter` | 연속 중복 제거, 비연속 중복 유지 |
| `TestSegmentIds` | 순차 zero-padded ID |
| `TestRounding` | timestamp 소수점 3자리 반올림 |
| `TestSixtySecondCoverage` | 60초 3청크 전체 커버, 40초 이후 발화 포함 확인 |

전체 단위 테스트 실행:

```bash
python -m pytest tests/unit/ -v
```

---

### 전후 성능 비교 벤치마크

GPU 없이 실행 가능한 후처리 품질 비교 스크립트.

```bash
# 1단계: 수정 후 코드 측정 (현재 브랜치)
python scripts/benchmark_asr_postprocess.py --save new

# 2단계: 수정 전 코드로 전환
git stash

# 3단계: 수정 전 코드 측정
python scripts/benchmark_asr_postprocess.py --save old

# 4단계: 코드 복원 및 비교표 출력
git stash pop
python scripts/benchmark_asr_postprocess.py --compare
```

---

## 벤치마크 결과

9개 시나리오(실제 Whisper 출력 문제 유형 기반) 기준.

### Before (수정 전)

```
시나리오                         세그먼트     커버리지    오류수   결과
------------------------------------------------------------------------
정상 입력                         5/5   100.0%      0   ✓
None end timestamp            3/3    65.0%      0   ✗
중간 None end timestamp         3/3    73.3%      0   ✗
60초 오디오 3청크 (핵심 버그 시나리오)  6/6   100.0%      0   ✓
청크 경계 겹침                      4/3   100.0%      1   ✗
Whisper 환각 중복 루프              5/3   100.0%      2   ✗
빈 텍스트 세그먼트                    5/3   100.0%      3   ✗
역방향 timestamp                 3/3    60.0%      1   ✗
복합 문제                         7/5    91.1%      3   ✗
------------------------------------------------------------------------
합계                                   87.7%     10건   2/9 통과
```

### After (수정 후)

```
시나리오                         세그먼트     커버리지    오류수   결과
------------------------------------------------------------------------
정상 입력                         5/5   100.0%      0   ✓
None end timestamp            3/3   100.0%      0   ✓
중간 None end timestamp         3/3   100.0%      0   ✓
60초 오디오 3청크 (핵심 버그 시나리오)  6/6   100.0%      0   ✓
청크 경계 겹침                      3/3    80.0%      0   ✓
Whisper 환각 중복 루프              3/3    66.7%      0   ✓
빈 텍스트 세그먼트                    3/3    60.0%      0   ✓
역방향 timestamp                 3/3    67.5%      0   ✓
복합 문제                         5/5    88.9%      0   ✓
------------------------------------------------------------------------
합계                                   84.8%      0건   9/9 통과
```

### 전후 비교 요약

| 지표 | Before | After | 변화 |
|------|--------|-------|------|
| 통과율 | 2/9 (22%) | **9/9 (100%)** | **+7개 (+78%p)** |
| 총 오류 | 10건 | **0건** | **-10건** |
| 평균 커버리지 | 87.7% | 84.8% | -2.9%p |

**커버리지 소폭 감소에 대하여**

수정 후 평균 커버리지가 2.9%p 낮아진 것은 퇴보가 아니다.
구 버전은 환각 중복·빈 텍스트를 세그먼트로 포함했기 때문에 커버리지 수치가 높게 측정됐다.
신 버전은 이를 필터링하므로 실제 유효 발화만 커버리지에 포함된다.

### 시나리오별 개선 내역

| 시나리오 | Before | After | 결과 |
|---------|--------|-------|------|
| 정상 입력 | 5/5, 100%, err=0 | 5/5, 100%, err=0 | 유지 |
| None end timestamp | 3/3, 65%, err=0 | 3/3, 100%, err=0 | **FIXED** |
| 중간 None end timestamp | 3/3, 73%, err=0 | 3/3, 100%, err=0 | **FIXED** |
| 60초 3청크 | 6/6, 100%, err=0 | 6/6, 100%, err=0 | 유지 |
| 청크 경계 겹침 | 4/3, 100%, err=1 | 3/3, 80%, err=0 | **FIXED** |
| Whisper 환각 중복 | 5/3, 100%, err=2 | 3/3, 67%, err=0 | **FIXED** |
| 빈 텍스트 세그먼트 | 5/3, 100%, err=3 | 3/3, 60%, err=0 | **FIXED** |
| 역방향 timestamp | 3/3, 60%, err=1 | 3/3, 68%, err=0 | **FIXED** |
| 복합 문제 | 7/5, 91%, err=3 | 5/5, 89%, err=0 | **FIXED** |

---

## 한계 및 주의사항

- **`batch_size=1` 성능 영향**: 배치 처리 비활성화로 GPU 처리량이 감소한다.
  단일 파일을 순차 처리하는 현재 아키텍처에서는 실질적 차이가 크지 않다.
  향후 병렬 처리가 필요하면 transformers 버전 업그레이드(5.x, torch 2.5+ 필요)를 검토한다.

- **`batch_size` 버그는 GPU 실측 필요**: 본 벤치마크는 후처리 로직만 측정한다.
  `batch_size=1`로 인한 40초 잘림 버그 수정 효과는 실제 GPU 환경에서 60초 이상
  오디오를 실행해야 완전히 검증된다.

- **환각 중복 필터**: 연속 동일 텍스트만 제거한다. 비연속 반복(A→B→A)은 유지된다.
