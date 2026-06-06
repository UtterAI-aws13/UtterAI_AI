# AI 파이프라인 병목 최소화 가이드

UtterAI 분석 파이프라인에서 발생하는 AI 모델 병목의 원인과 해결 방법을 단계별로 정리합니다.

---

## 1. 파이프라인 병목 프로파일

각 단계의 실행 특성을 기준으로 병목 강도를 분류합니다.

| 단계 | 모델 | 처리 시간 (45초 오디오 기준) | 리소스 | 병목 수준 |
|---|---|---|---|---|
| 음성 전처리 | ffmpeg | ~0.5초 | CPU | 낮음 |
| VAD | Silero VAD (ONNX) | ~0.3초 | CPU | 낮음 |
| **화자 분리** | **pyannote 3.1** | **~15~30초** | **GPU (embedding-heavy)** | **높음** |
| **STT 전사** | **Whisper large-v3-turbo** | **~10~20초** | **GPU (seq2seq)** | **높음** |
| 발화 정렬 + 지표 | alignment.py + Kiwi | ~1초 | CPU | 낮음 |
| RAG 검색 | KURE-v1 + pgvector | ~1~3초 | CPU + DB | 중간 |
| **LLM 리포트** | **EXAONE 2.4B** | **~20~60초** | **GPU (autoregressive)** | **최고** |

핵심 병목 3개: pyannote → Whisper → EXAONE 순으로 처리 시간 비중이 높습니다.

---

## 2. 가장 큰 병목: 모델 Cold Start

### 문제

모델을 Job마다 새로 로드하면 pyannote + Whisper + EXAONE 합산 초기 로드 시간이 1~2분 소요됩니다.

```
pyannote load:  ~30초  (1.62 GB 모델, embedding 포함)
Whisper load:   ~10초  (1.5 GB)
EXAONE load:    ~20초  (5 GB)
───────────────────────────────
합계 cold start: ~60~90초
```

이 시간은 실제 추론 시간보다 길거나 동일합니다.

### 해결: Pod 시작 시 1회 로드, 이후 predict()만 호출

```python
# app/workers/analysis_worker.py

# Worker 프로세스 시작 시 1회만 실행
def startup():
    global whisper_model, pyannote_pipeline, exaone_model

    pyannote_pipeline = PyannoteWrapper(settings.diarization_model_name, hf_token=settings.hf_token)
    pyannote_pipeline.load()

    whisper_model = WhisperASRWrapper(settings.asr_model_name, device="cuda")
    whisper_model.load()

    exaone_model = EXAONEWrapper(settings.llm_model_name, device="cuda")
    exaone_model.load()

# 이후 SQS 메시지마다 실행 — load() 없음
def handle_job(job_id: str, audio_path: str):
    speaker_segments = pyannote_pipeline.predict(audio_path)
    asr_result       = whisper_model.predict(audio_path)
    report           = generate_report(..., exaone_model)
```

**효과**: Job당 처리 시간에서 cold start 60~90초 제거.

---

## 3. GPU 메모리 관리

### 현재 모델별 VRAM 요구량

```
pyannote speaker-diarization-3.1   ~800 MB ~ 1.2 GB (추론 중 peak)
Whisper large-v3-turbo             ~1.5 GB
EXAONE-3.5-2.4B (bfloat16)        ~5.0 GB
────────────────────────────────────────────
합계 동시 상주: ~7.5 ~ 7.7 GB
T4 16 GB 기준 여유: ~8 GB
```

T4 16 GB 하나에 세 모델을 전부 올릴 수 있으나, 추론 중 피크 메모리가 초과하면 CUDA OOM이 발생합니다.

### 해결 1: 추론 순서를 직렬로 고정해 peak VRAM 시점 분산

pyannote와 Whisper는 동시에 실행되지 않습니다. 모델을 `cuda`에 올린 채 유지하되 추론을 직렬로 실행하면 peak가 겹치지 않습니다.

```python
# GPU 사용 시점이 겹치지 않는 직렬 순서
speaker_segments = pyannote_pipeline.predict(audio_path)   # pyannote GPU 사용 → 유휴
asr_result       = whisper_model.predict(audio_path)        # Whisper GPU 사용 → 유휴
report           = generate_report(..., exaone_model)       # EXAONE GPU 사용
```

### 해결 2: EXAONE 4-bit 양자화 (VRAM 절감)

`bfloat16` 5 GB → `NF4` 약 1.5 GB로 줄입니다. SOAP Note 생성 품질 손실은 경미합니다.

```python
from transformers import BitsAndBytesConfig
import torch

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)

model = AutoModelForCausalLM.from_pretrained(
    "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct",
    quantization_config=bnb_config,
    device_map="cuda",
)
```

**효과**: EXAONE VRAM 5 GB → ~1.5 GB. 세 모델 합계 ~4.5 GB로 T4에서 더 안정적.

**설치 필요 패키지**: `pip install bitsandbytes`

---

## 4. pyannote 병목 최소화

### 구조

pyannote는 세그멘테이션 → 임베딩 → 클러스터링 세 단계를 순차로 실행합니다.
45초 오디오 기준 15~30초 소요됩니다.

### 해결 1: `min_speakers` / `max_speakers` 힌트 제공

화자 수를 알고 있으면 클러스터링 탐색 범위를 고정합니다.

```python
# 어린이 언어치료 세션: CHILD + THERAPIST 항상 2명
diarization = self.pipeline(
    {"waveform": waveform, "sample_rate": sample_rate},
    min_speakers=2,
    max_speakers=2,
)
```

**효과**: 클러스터링 단계 탐색 범위 고정 → 10~20% 속도 향상.

### 해결 2: 전처리 완료된 16kHz mono WAV 전달

pyannote 내부에서 리샘플링이 발생하면 추가 시간이 소요됩니다.
`preprocess_audio`에서 이미 16 kHz mono로 변환하므로 해당 파일을 직접 전달합니다.

```python
# dev_run.py / analysis_worker.py
audio_meta = preprocess_audio(audio_path, tmp_wav)  # 16kHz mono 변환
speaker_segments = diarize.predict(tmp_wav)          # 전처리 완료 파일 사용
```

### 해결 3: DiarizeOutput 호환 처리 (pyannote ≥ 3.3)

pyannote 3.3 이상에서 `pipeline()` 반환 타입이 `DiarizeOutput`으로 변경되었습니다.
`.speaker_diarization` 속성으로 `Annotation`을 꺼내야 `itertracks()`를 호출할 수 있습니다.

```python
diarization = self.pipeline({"waveform": waveform, "sample_rate": sample_rate})

# pyannote ≥ 3.3: DiarizeOutput → Annotation 추출
if hasattr(diarization, "speaker_diarization"):
    diarization = diarization.speaker_diarization
```

`app/models/diarization_pyannote.py`에 이미 적용되어 있습니다.

---

## 5. Whisper 병목 최소화

### 해결 1: Scaled Dot-Product Attention (T4 환경)

T4 GPU는 Flash Attention 2를 지원하지 않습니다. PyTorch 2.0+의 `sdpa`를 사용합니다.

```python
model = AutoModelForSpeechSeq2Seq.from_pretrained(
    "openai/whisper-large-v3-turbo",
    torch_dtype=torch.float16,
    attn_implementation="sdpa",   # T4(g4dn) 환경
    device_map="cuda",
)
```

A10G 이상(g5 시리즈)에서는 `attn_implementation="flash_attention_2"`로 30~40% 추가 향상이 가능합니다.

### 해결 2: `torch.compile()` (PyTorch 2.0+)

JIT 컴파일로 이후 추론 속도 20~30% 향상. 컴파일 비용은 첫 번째 추론에서만 발생합니다.

```python
model = torch.compile(model)
```

첫 번째 `predict()` 호출 시 컴파일 시간(~30초)이 추가되므로 Pod warm-up 단계에서 더미 입력으로 한 번 실행합니다.

```python
def warmup_whisper(model, processor):
    dummy_audio = {"array": [0.0] * 16000, "sampling_rate": 16000}  # 1초 무음
    inputs = processor(dummy_audio["array"], sampling_rate=16000, return_tensors="pt")
    inputs = inputs.to("cuda", dtype=torch.float16)
    with torch.no_grad():
        model.generate(**inputs, max_new_tokens=1)
```

---

## 6. EXAONE LLM 병목 최소화

EXAONE은 autoregressive 생성 방식으로 토큰 수에 비례해 처리 시간이 늘어납니다.

### 해결 1: `max_new_tokens` 상한 설정

SOAP Note는 구조화된 JSON 출력입니다. 불필요하게 긴 생성을 방지합니다.

```python
output = model.generate(
    **inputs,
    max_new_tokens=512,   # SOAP Note JSON 기준 충분한 상한
    do_sample=False,       # greedy decoding — 재현성 + 속도 우선
)
```

### 해결 2: 시스템 프롬프트 prefix KV Cache

동일한 시스템 프롬프트(SOAP Note 포맷 지시문)를 반복 사용할 때 `past_key_values`를 재사용하면 prefix 부분의 attention 계산을 건너뜁니다.

```python
from transformers import DynamicCache

# 시스템 프롬프트 prefix를 한 번만 계산
system_cache = DynamicCache()
with torch.no_grad():
    outputs = model(**system_inputs, past_key_values=system_cache, use_cache=True)
    system_cache = outputs.past_key_values

# 이후 각 Job에서 system_cache 재사용
output = model.generate(
    **job_inputs,
    past_key_values=system_cache,
    max_new_tokens=512,
)
```

### 해결 3: Speculative Decoding (운영 고도화 단계)

EXAONE-3.5-2.4B를 draft model, EXAONE-3.5-7.8B를 verifier로 사용하면 생성 속도 2~3배 향상.
VRAM이 추가로 필요하므로 `g5.2xlarge` (A10G 24 GB) 이상 노드에서 적용합니다.

---

## 7. GPU Worker 큐 분리 전략

### 현재 구조: 단일 GPU 큐 (순차 처리)

```
gpu-analysis-queue
      │
      ▼
GPU Worker Pod (pyannote → Whisper → EXAONE 순차)
```

한 Job이 GPU를 점유하면 다음 Job은 SQS에서 대기합니다.
세션이 몰릴 때 처리 지연이 선형으로 증가합니다.

### 개선: 2-Queue 분리로 EXAONE 격리

```
gpu-inference-queue               report-analysis-queue
      │                           │
      ▼                           ▼
ML Worker (g4dn.xlarge)     LLM Worker (g5.xlarge)
pyannote + Whisper           EXAONE
      │                           ▲
      └── S3 중간 결과 저장 ───────┘
          + report-analysis-queue 메시지 발행
```

pyannote + Whisper 결과를 S3에 저장하고 `report-analysis-queue`에 메시지를 넣으면 ML Worker와 LLM Worker가 독립적으로 스케일링됩니다.

**효과**: 세션이 몰릴 때 ML Worker 3개 + LLM Worker 2개처럼 독립 스케일링 가능.

| Worker | 인스턴스 | 담당 | 스케일링 기준 |
|---|---|---|---|
| ML Worker | g4dn.xlarge (T4 16 GB) | pyannote + Whisper | `gpu-inference-queue` 깊이 |
| LLM Worker | g5.xlarge (A10G 24 GB) | EXAONE | `report-analysis-queue` 깊이 |

---

## 8. EFS 모델 캐시 마운트 (스케일업 Cold Start 제거)

### 문제

EKS에서 GPU Worker Pod가 0→1로 스케일업되면 모델(합계 ~8 GB)을 다시 다운로드합니다.
기본 `~/.cache/huggingface`는 Pod 재시작 시 초기화됩니다.
스케일업 → 실제 추론 시작까지 3~5분 소요.

### 해결: EFS PersistentVolume으로 캐시 공유

```yaml
# EFS PersistentVolumeClaim
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: hf-model-cache
spec:
  accessModes: [ReadWriteMany]   # 여러 Pod 동시 마운트 가능
  storageClassName: efs-sc
  resources:
    requests:
      storage: 50Gi
```

```yaml
# GPU Worker Deployment
env:
  - name: HF_HOME
    value: /mnt/models/.cache/huggingface
  - name: TRANSFORMERS_OFFLINE
    value: "1"    # 다운로드 완료 후 오프라인 모드 활성화

volumeMounts:
  - name: model-cache
    mountPath: /mnt/models

volumes:
  - name: model-cache
    persistentVolumeClaim:
      claimName: hf-model-cache
```

**효과**: Pod 재시작 시 모델 재다운로드 없음. 스케일업 cold start 3~5분 → 10~20초로 단축.

---

## 9. 단계별 처리 시간 모니터링

실제 병목을 파악하려면 각 단계의 처리 시간을 CloudWatch Custom Metric으로 기록합니다.

```python
import time
import boto3

cw = boto3.client("cloudwatch", region_name="ap-northeast-2")

def emit_duration(step: str, duration_sec: float, job_id: str):
    cw.put_metric_data(
        Namespace="UtterAI/Pipeline",
        MetricData=[{
            "MetricName": "StepDuration",
            "Dimensions": [
                {"Name": "Step",  "Value": step},
                {"Name": "JobId", "Value": job_id},
            ],
            "Value": duration_sec,
            "Unit": "Seconds",
        }]
    )

# 사용 예시
t0 = time.perf_counter()
speaker_segments = diarize.predict(audio_path)
emit_duration("pyannote_diarization", time.perf_counter() - t0, job_id)
```

**알람 임계값 권장값**

| Step | CloudWatch 알람 임계값 |
|---|---|
| `audio_preprocess` | > 5초 |
| `silero_vad` | > 3초 |
| `pyannote_diarization` | > 45초 |
| `whisper_asr` | > 60초 |
| `alignment_metrics` | > 10초 |
| `rag_retrieval` | > 5초 |
| `exaone_report` | > 120초 |

---

## 10. 최적화 우선순위 요약

| 우선순위 | 최적화 항목 | 난이도 | 기대 효과 |
|---|---|---|---|
| 1 | Pod 시작 시 모델 1회 로드 | 낮음 | cold start 60~90초 제거 |
| 2 | pyannote `min/max_speakers=2` 힌트 | 낮음 | 클러스터링 10~20% 단축 |
| 3 | EXAONE `max_new_tokens=512` 상한 설정 | 낮음 | 생성 시간 상한 제어 |
| 4 | EFS 캐시 마운트 | 중간 | 스케일업 cold start 제거 |
| 5 | EXAONE 4-bit 양자화 (NF4) | 중간 | VRAM 5 GB → 1.5 GB |
| 6 | Whisper `attn_implementation="sdpa"` | 낮음 | 어텐션 연산 최적화 |
| 7 | Whisper `torch.compile()` | 중간 | 추론 20~30% 단축 |
| 8 | ML Worker / LLM Worker 큐 분리 | 높음 | 독립 스케일링 가능 |
| 9 | Speculative Decoding (EXAONE) | 높음 | 생성 속도 2~3배 향상 |
