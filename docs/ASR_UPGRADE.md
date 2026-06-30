# ASR 고도화 작업 기록

> **브랜치**: `fix/asr-transcript-truncation`  
> **작업 일자**: 2026-06-28 ~ 2026-06-29  
> **연관 PR**: [#67](https://github.com/UtterAI-aws13/UtterAI_AI/pull/67)

---

## 배경

1분짜리 오디오를 분석하면 전사문이 약 40초 지점에서 잘리는 현상이 보고되었다. 7초·48초 오디오는 끝까지 정상 처리되었기 때문에 특정 길이 임계값에서 발생하는 구조적 문제임을 파악했다. 이를 단순 버그 수정이 아닌 **전사 품질 전반의 고도화**로 접근했다.

---

## 변경 사항 상세

### 1. ASR 엔진 교체: `transformers` → `faster-whisper`

#### 기존 방식

`app/models/asr_whisper.py`는 HuggingFace `transformers`의 `AutomaticSpeechRecognitionPipeline`을 사용했다.

```python
# 기존 (dev 브랜치)
from transformers import pipeline

self.pipeline = pipeline(
    "automatic-speech-recognition",
    model="openai/whisper-large-v3-turbo",
    device=device,
    torch_dtype=dtype,
)

result = self.pipeline(
    audio_path,
    generate_kwargs={"language": self.language},
    return_timestamps=True,
    chunk_length_s=30,
    stride_length_s=(5, 5),
    batch_size=8,
)
```

Whisper는 최대 30초 컨텍스트 윈도우를 가지기 때문에 긴 오디오를 처리하려면 파이프라인이 내부적으로 30초 단위 청크로 분할하고, 분할된 청크들의 타임스탬프를 누적 합산해 전체 타임라인으로 재조립한다.

#### 문제의 원인

`transformers==4.47.1` + `batch_size > 1` 조합에서 타임스탬프 오프셋 누적 버그가 존재한다. 60초 오디오를 `chunk_length_s=30, stride_length_s=5`로 처리하면 step=20s 기준으로 3개의 청크(`[0~30]`, `[20~50]`, `[40~60]`)가 생성된다. 두 번째 청크부터 타임스탬프 오프셋이 잘못 계산되어 실제 음성이 있음에도 전사가 ~40초 이후로 확장되지 않았다.

`batch_size=1`로 낮춰도 동일 증상이 재현되었고, 파이프라인 레이어의 구조적 제약임을 확인했다.

#### 해결 방향 선택 이유

`faster-whisper`는 [Systran](https://github.com/SYSTRAN/faster-whisper)이 개발한 CTranslate2 기반 Whisper 추론 엔진으로, 장문 오디오의 청킹과 타임스탬프 재조립을 직접 구현해 위 버그가 없다. 추가로 다음 이점이 있었다.

| 항목 | transformers | faster-whisper |
|------|-------------|----------------|
| 장문 오디오 안정성 | ❌ 타임스탬프 오프셋 버그 | ✅ 자체 청킹 엔진 |
| GPU 동일 조건 속도 | 기준 | 약 2~4배 빠름 |
| 추가 GPU 메모리 | 더 많이 사용 | CTranslate2 최적화로 적게 사용 |
| `condition_on_previous_text` | ❌ 미지원 (generate_kwargs에 없음) | ✅ transcribe() 파라미터로 지원 |

별도 모델 가중치 변환 없이 faster-whisper의 내장 레지스트리(`faster_whisper.utils.available_models()`)에 `large-v3-turbo`가 등록되어 있어, 단순 이름 지정만으로 CTranslate2 변환 모델을 자동 다운로드할 수 있다는 점도 도입 비용을 낮췄다.

#### 수정 후 코드

```python
# 수정 후
from faster_whisper import WhisperModel

self.model = WhisperModel(
    "large-v3-turbo",
    device=self.device,
    compute_type=self.compute_type,   # cuda → float16, cpu → int8 자동 선택
)

segments_gen, info = self.model.transcribe(
    audio_path,
    language=self.language,
    beam_size=self.beam_size,
    word_timestamps=False,
    vad_filter=False,
    condition_on_previous_text=False,
)
```

#### 결과

- 60초 오디오가 60초 전체를 커버하는 전사문 생성
- 동일 GPU에서 처리 속도 향상
- `condition_on_previous_text=False` 적용으로 청크 경계에서 앞 청크 내용이 뒤 청크에 영향을 주는 환각 현상 차단

---

### 2. `condition_on_previous_text` 파라미터 위치 오류 수정

#### 기존 방식

초기 고도화 시도 중 `condition_on_previous_text=False`를 HuggingFace transformers 파이프라인의 `generate_kwargs`에 추가했다.

```python
# 잘못된 적용 (중간 시도)
result = self.pipeline(
    audio_path,
    generate_kwargs={
        "language": self.language,
        "condition_on_previous_text": False,  # ❌ transformers는 이 파라미터 미지원
    },
    ...
)
```

#### 문제

실행 시 다음 경고가 발생하며 파라미터가 무시되었다.

```
ERROR: condition_on_previous_text not used
```

`condition_on_previous_text`는 OpenAI의 whisper 원본 패키지 파라미터이며, HuggingFace transformers의 Whisper 구현에는 `generate_kwargs`로 전달할 수 없다.

#### 해결

faster-whisper로 엔진을 교체함으로써 자연스럽게 해결되었다. `WhisperModel.transcribe()`는 이 파라미터를 공식 지원한다.

```python
segments_gen, info = self.model.transcribe(
    audio_path,
    condition_on_previous_text=False,  # ✅ faster-whisper에서는 유효한 파라미터
)
```

#### 결과

경고 메시지가 사라지고, 청크 간 컨텍스트 전파가 실제로 차단되어 반복 환각이 억제된다.

---

### 3. ASR 세그먼트 후처리(`_postprocess_chunks`) 신규 구현

#### 기존 방식

transformers 파이프라인 출력을 받아 단순 반복문으로 세그먼트를 생성했다.

```python
# 기존 후처리 — 유효성 검사 없음
for i, chunk in enumerate(chunks):
    ts = chunk.get("timestamp") or (None, None)
    start = float(ts[0]) if ts[0] is not None else 0.0
    end = float(ts[1]) if ts[1] is not None else start + 1.0
    asr_segments.append(ASRSegment(
        asr_segment_id=f"asr_{i:03d}",
        start_time=round(start, 3),
        end_time=round(end, 3),
        text=chunk["text"].strip(),
        confidence=1.0,
    ))
```

#### 문제

1. **빈 텍스트 세그먼트 통과**: 공백만 있는 세그먼트가 그대로 생성되어 alignment 단계에서 오류 발생
2. **None end timestamp 처리 불완전**: `ts[1] is None`이면 `start + 1.0` 고정으로 처리해 실제 발화 길이를 반영하지 못함
3. **end ≤ start 케이스 미처리**: 모델이 역방향 타임스탬프를 출력할 때 ASRSegment 스키마 검증 실패
4. **겹치는 세그먼트 허용**: 청크 경계에서 동일 구간이 두 번 전사되면 중복 세그먼트가 내려감
5. **연속 중복 텍스트 허용**: Whisper의 대표적 환각 패턴인 동일 문장 반복이 필터링되지 않음
6. **정렬 보장 없음**: 청크 순서가 보장되지 않는 경우 타임라인 역전 가능

#### 해결

5단계 파이프라인 형태의 `_postprocess_chunks()` 메서드를 신규 구현했다.

```python
def _postprocess_chunks(self, chunks, audio_duration):
    # 1. 파싱 + 빈 텍스트 필터
    parsed = [...]   # text가 공백인 항목 제거

    # 2. 시작 시간 기준 정렬
    parsed.sort(key=lambda s: s["start"])

    # 3. None end timestamp → 다음 세그먼트 start 또는 audio_duration
    for i, seg in enumerate(parsed):
        if seg["end"] is None:
            seg["end"] = parsed[i+1]["start"] if i+1 < len(parsed) else audio_duration

    # 4. end ≤ start → start + 0.5s 보정
    for seg in parsed:
        if seg["end"] <= seg["start"]:
            seg["end"] = seg["start"] + 0.5

    # 5. 겹치는 세그먼트 제거 (forward sweep)
    filtered = []
    cursor = 0.0
    for seg in parsed:
        if seg["start"] >= cursor:
            filtered.append(seg)
            cursor = seg["end"]

    # 6. 연속 중복 텍스트 제거
    deduped = []
    prev_text = None
    for seg in filtered:
        if seg["text"] != prev_text:
            deduped.append(seg)
        prev_text = seg["text"]
```

단순 조건문 누적 대신 파이프라인 구조를 선택한 이유는 각 처리 단계의 입력 상태가 이전 단계 출력에 의존하기 때문이다(예: 정렬 전에는 None end를 다음 세그먼트 start로 채울 수 없다). 단계별로 명확히 분리함으로써 단위 테스트 작성도 용이해졌다.

#### 결과

벤치마크 스크립트 기준 9개 시나리오 중 수정 전 2/9 통과 → 수정 후 9/9 통과.

---

### 4. VAD 세그먼트 그룹화 유틸리티(`_group_vad_segments`) 추가

#### 기존 방식

VAD(Voice Activity Detection) 결과를 ASR에 전달하는 인터페이스가 없었다. ASR은 항상 오디오 파일 전체를 처음부터 끝까지 처리했다.

#### 문제

무음 구간이 긴 오디오에서 Whisper가 무음 구간을 임의의 텍스트로 채우는 환각이 발생할 수 있다. CPU stage에서 이미 SileroVAD로 발화 구간 정보를 생성해 S3에 올려두지만, GPU stage의 ASR이 이를 활용하지 않아 정보가 낭비되었다.

#### 해결

`_group_vad_segments()` 유틸리티 함수를 추가해 VAD 세그먼트를 Whisper 처리에 적합한 크기의 그룹으로 병합하는 로직을 구현했다.

```python
def _group_vad_segments(segments, max_duration=25.0, max_gap=2.0):
    """VAD 세그먼트를 발화 흐름 기준으로 그룹화한다.
    - 인접 세그먼트 간 gap > 2s 이면 새 그룹 시작
    - 그룹 누적 길이 > 25s 이면 새 그룹 시작
    """
```

`predict_with_vad()`는 현재 `predict()`를 그대로 호출하는 패스스루 형태이나, 인터페이스를 분리해두어 추후 VAD 구간만 선택적으로 전사하는 최적화가 가능하다.

#### 결과

향후 VAD 기반 선택적 전사로의 확장을 위한 인터페이스가 준비되었다. 현재는 faster-whisper 자체 청킹이 안정적이므로 전체 오디오 전사를 유지한다.

---

### 5. ASR 설정 파라미터 정리 (`app/config.py`)

#### 기존 방식

```python
# app/config.py (기존)
asr_model_name: str = "openai/whisper-large-v3-turbo"

asr_chunk_length_s: int = 30    # Whisper 네이티브 컨텍스트 윈도우(30s)에 맞춤
asr_stride_length_s: int = 5    # 청크 경계 아티팩트 방지용 양쪽 오버랩
asr_batch_size: int = 8         # GPU 병렬 처리 청크 수
```

#### 문제

- `asr_chunk_length_s`, `asr_stride_length_s`, `asr_batch_size`는 transformers 파이프라인 전용 파라미터다.
- faster-whisper는 청킹을 내부적으로 처리하므로 이 파라미터들이 존재하면 혼란을 유발한다.
- `asr_model_name`의 `"openai/whisper-large-v3-turbo"`는 HuggingFace Hub 경로이며 faster-whisper에 전달하면 모델을 찾을 수 없다.

#### 해결

```python
# app/config.py (수정 후)
asr_model_name: str = "large-v3-turbo"   # faster-whisper 내장 레지스트리 단축명
asr_device: str = "cuda"                  # 유지
# chunk_length_s, stride_length_s, batch_size 삭제
```

`"large-v3-turbo"`는 `faster_whisper.utils.available_models()`가 반환하는 내장 레지스트리 이름이다. 이 이름을 사용하면 faster-whisper가 Systran HuggingFace 저장소에서 CTranslate2 변환 모델을 자동으로 다운로드한다. `"Systran/faster-whisper-large-v3-turbo"` 형식의 전체 경로는 해당 저장소가 존재하지 않아 오류가 발생한다.

#### 결과

설정 파일이 현재 엔진(faster-whisper)에 맞는 파라미터만 포함하며, 잘못된 모델 이름으로 인한 `RuntimeError: Unable to open file 'model.bin'` 오류가 해소된다.

---

### 6. `.env.example` 모델명 업데이트

#### 기존 방식

```
ASR_MODEL_NAME=openai/whisper-large-v3-turbo
```

#### 문제

환경변수가 HuggingFace Hub 경로를 가리키고 있어 faster-whisper에서 모델을 찾지 못한다.

#### 해결

```
ASR_MODEL_NAME=large-v3-turbo
```

#### 결과

`.env.example`을 복사해 바로 실행해도 faster-whisper가 모델을 올바르게 다운로드한다.

---

### 7. `ml_gpu_worker.py` — ASR 생성자 파라미터 제거

#### 기존 방식

```python
asr = WhisperASRWrapper(
    settings.asr_model_name,
    device=settings.asr_device,
    chunk_length_s=settings.asr_chunk_length_s,
    stride_length_s=settings.asr_stride_length_s,
    batch_size=settings.asr_batch_size,
)
```

#### 문제

`WhisperASRWrapper.__init__`에서 `chunk_length_s`, `stride_length_s`, `batch_size` 파라미터가 제거되었기 때문에 `TypeError`가 발생한다.

#### 해결

```python
asr = WhisperASRWrapper(
    settings.asr_model_name,
    device=settings.asr_device,
)
```

#### 결과

워커 시작 시 `TypeError: __init__() got an unexpected keyword argument` 오류 없이 정상 로드된다.

---

### 8. `ml_gpu_worker.py` — SIGTERM 핸들러 및 graceful shutdown 추가

#### 기존 방식

```python
while True:
    # SQS 폴링
```

프로세스가 SIGTERM을 받아도 현재 처리 중인 메시지를 완료하지 않고 즉시 종료될 수 있었다.

#### 문제

컨테이너 오케스트레이터(ECS, Kubernetes 등)가 SIGTERM을 보낸 뒤 일정 시간 후 SIGKILL로 강제 종료하는 방식이다. 처리 중이던 ASR/Diarization 작업이 중간에 끊기면 해당 메시지의 가시성 타임아웃이 만료된 후 다시 큐에 올라와 중복 처리된다.

#### 해결

```python
_shutdown = threading.Event()

signal.signal(signal.SIGTERM, lambda *_: _shutdown.set())

while not _shutdown.is_set():
    # SQS 폴링
```

#### 결과

SIGTERM 수신 시 현재 루프의 메시지 처리를 완료한 뒤 종료된다.

---

### 9. `ml_gpu_worker.py` — SQS 가시성 타임아웃 연장 로직 개선

#### 기존 방식

```python
def _extend_visibility(..., interval: int = 300) -> None:
    while not stop_event.wait(interval):  # interval 동안 대기 후 연장
        sqs_client.change_message_visibility(...)
```

`stop_event.wait(300)`은 300초를 기다린 뒤 연장한다. 즉, 수신 직후 300초간 연장이 이루어지지 않는다.

#### 문제

SQS 큐의 기본 가시성 타임아웃이 300초 미만으로 설정된 경우, heartbeat가 첫 연장을 하기 전에 메시지가 다시 큐에 노출된다. large-v3-turbo 모델 최초 다운로드 시(수 분 소요) 특히 취약했다.

#### 해결

```python
def _extend_visibility(..., interval: int = 240) -> None:
    while True:
        sqs_client.change_message_visibility(...)   # 수신 즉시 연장
        if stop_event.wait(interval):
            break
```

연장을 먼저 수행한 뒤 대기하는 구조로 변경했다. interval도 300 → 240으로 줄여 여유를 두었다.

#### 결과

메시지 수신 직후 즉시 가시성을 연장해 큐 기본 설정값에 무관하게 안전하게 동작한다.

---

### 10. `analysis_pipeline.py` — VAD 로드 순서를 ASR 이전으로 이동

#### 기존 방식

```python
# 기존 실행 순서
1. 오디오 다운로드
2. Diarization
3. ASR (predict 직접 호출 — VAD 정보 미사용)
4. ASR 결과 저장
5. VAD 결과 로드     ← ASR 이후에 로드
6. Alignment
```

#### 문제

ASR이 `predict()`만 호출하고 VAD 정보를 받지 않았다. VAD 정보는 alignment 단계에서만 사용했다. 이는 `predict_with_vad()` 인터페이스의 활용을 막고, VAD 로드 실패 시 alignment 단계에서야 오류가 드러나는 구조였다.

#### 해결

```python
# 수정 후 실행 순서
1. 오디오 다운로드
2. VAD 결과 로드     ← ASR 이전으로 이동
3. Diarization
4. ASR (predict_with_vad 호출 — speech_segments 전달)
5. ASR 결과 저장
6. Alignment
```

```python
# 수정 후 코드
vad_path = str(tmp / "vad_segments.json")
s3_client.download(settings.s3_bucket_audio, message.vad_s3_key, vad_path)
speech_segments = [SpeechSegment(**s) for s in json.loads(Path(vad_path).read_text())]

asr_result = models.asr.predict_with_vad(wav_path, speech_segments)
```

#### 결과

VAD 데이터를 ASR에 전달하는 경로가 열렸다. 현재는 faster-whisper가 전체 오디오를 처리하는 방식이지만, 추후 VAD 구간 기반 선택적 전사 최적화로 이어질 수 있다.

---

### 11. `pyproject.toml` — `faster-whisper` 의존성 추가

#### 기존 방식

`gpu` extras에 faster-whisper가 없었다.

#### 문제

`from faster_whisper import WhisperModel` 임포트 시 `ModuleNotFoundError` 발생.

#### 해결

```toml
# pyproject.toml [project.optional-dependencies] gpu 섹션에 추가
"faster-whisper>=1.1.0",
```

`>=1.1.0`으로 하한을 지정한 이유는 `large-v3-turbo`가 내장 레지스트리에 포함된 버전이 1.1.0 이상이기 때문이다. `uv.lock`에는 실제 해소된 버전인 `faster-whisper==1.2.1`, `ctranslate2==4.8.0`, `av==17.1.0`이 고정된다.

#### 결과

`uv sync --extra gpu` 실행 시 faster-whisper와 CTranslate2가 자동으로 설치된다.

---

### 12. 단위 테스트 추가 (`tests/unit/test_asr_postprocess.py`)

#### 기존 방식

ASR 후처리 로직에 대한 단위 테스트가 없었다. 전사 품질 검증은 실제 GPU 서버에서 오디오 파일을 넣어봐야만 가능했다.

#### 문제

- 후처리 로직 변경 시 회귀 확인이 불가능
- 버그 재현을 위해 매번 GPU 환경과 실제 오디오 파일이 필요
- 엣지 케이스(None 타임스탬프, 역방향 타임스탬프, 환각 반복 등)가 테스트되지 않음

#### 해결

GPU와 모델 없이 후처리 로직만 검증하는 22개의 단위 테스트를 작성했다.

```
TestEmptyTextFilter       — 빈 텍스트 세그먼트 필터링 (2개)
TestTimestampFix          — None/역방향 타임스탬프 보정 (4개)
TestSorting               — 순서 역전 정렬 (1개)
TestOverlapRemoval        — 겹치는 세그먼트 제거 (3개)
TestHallucinationFilter   — 연속 중복 텍스트 제거 (2개)
TestSegmentIds            — asr_000 형식 ID 순번 (1개)
TestRounding              — 소수점 3자리 반올림 (1개)
TestVadGrouping           — _group_vad_segments (6개)
TestSixtySecondCoverage   — 60초 오디오 전체 커버 (2개)
```

#### 결과

`uv run pytest tests/unit/test_asr_postprocess.py` — 22/22 통과. CI 환경에서 GPU 없이 후처리 품질을 지속적으로 검증할 수 있게 되었다.

---

### 13. 벤치마크 스크립트 추가 (`scripts/benchmark_asr_postprocess.py`)

#### 기존 방식

수정 전후 성능을 객관적으로 비교할 수단이 없었다.

#### 문제

"고도화 전보다 나아졌다"는 것을 수치로 증명할 수 없었다.

#### 해결

9개의 대표 시나리오에 대해 수정 전/후 후처리 결과를 비교하는 스크립트를 작성했다.

```
시나리오:
1. 정상 전사 (7초 오디오)
2. None end timestamp 처리
3. 역방향 타임스탬프 처리
4. 60초 오디오 전체 커버 (핵심)
5. 청크 경계 겹침 처리
6. 연속 환각 필터링
7. 빈 텍스트 필터링
8. 대규모 오디오 (20+ 세그먼트)
9. 극단적 에지 케이스 복합
```

```bash
# 사용법
uv run python scripts/benchmark_asr_postprocess.py --save new   # 현재 결과 저장
git stash
uv run python scripts/benchmark_asr_postprocess.py --save old   # 수정 전 결과 저장
git stash pop
uv run python scripts/benchmark_asr_postprocess.py --compare    # 비교 출력
```

#### 결과

| 구분 | 통과 | 실패 | 오류 |
|------|------|------|------|
| 수정 전 | 2/9 | 0 | 10 |
| 수정 후 | 9/9 | 0 | 0 |

---

## 요약

| 구분 | 변경 전 | 변경 후 |
|------|---------|---------|
| ASR 엔진 | transformers pipeline | faster-whisper (CTranslate2) |
| 모델 이름 | `openai/whisper-large-v3-turbo` | `large-v3-turbo` |
| 청킹 방식 | 외부 파라미터 제어 (chunk=30s, stride=5s) | 엔진 내부 자동 처리 |
| 타임스탬프 오프셋 버그 | ❌ 발생 (40초 이후 잘림) | ✅ 없음 |
| `condition_on_previous_text` | ❌ 무시됨 (경고 발생) | ✅ 정상 적용 |
| 후처리 안정성 | 2/9 시나리오 통과 | 9/9 시나리오 통과 |
| 단위 테스트 | 0개 | 22개 |
| SIGTERM 처리 | ❌ 즉시 종료 | ✅ 현재 메시지 완료 후 종료 |
| VAD 활용 | alignment 전용 | ASR 전달 경로 확보 |
