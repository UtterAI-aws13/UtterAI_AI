# EKS Worker 아키텍처

UtterAI AI 모듈의 EKS 기반 Worker 배포 구조를 설명합니다.
분석 파이프라인을 CPU Worker와 GPU Worker로 나눠 리소스를 효율적으로 사용합니다.

---

## 1. 전체 구조 개요

```
Backend API
    │
    ├─ S3에 원본 음성 업로드
    └─ SQS에 분석 요청 발행
           │
           ├──────────────────────────────────────┐
           ▼                                      ▼
  SQS: cpu-analysis-queue              SQS: rag-ingest-queue
           │                                      │
           ▼                                      ▼
    CPU Worker Pod                       CPU Worker Pod
    (VAD, 정렬, 지표, RAG 검색)          (문서 chunk + 임베딩 저장)
           │
           │ Job 단계별 GPU 작업 위임
           ▼
  SQS: gpu-analysis-queue
           │
           ▼
    GPU Worker Pod
    (Whisper STT, pyannote 화자분리, EXAONE 리포트)
           │
           ▼
      S3 + RDS 저장
           │
           ▼
    Backend API 결과 조회
```

---

## 2. Worker 분리 기준

파이프라인의 각 단계를 리소스 특성에 따라 분류합니다.

| 단계 | 모델 | 리소스 | 담당 Worker |
|---|---|---|---|
| 음성 전처리 (ffmpeg) | — | CPU | CPU Worker |
| VAD 말소리 감지 | Silero VAD (ONNX) | CPU | CPU Worker |
| 화자 분리 | pyannote 3.1 | GPU | GPU Worker |
| STT 전사 | Whisper large-v3-turbo | GPU | GPU Worker |
| 발화 정렬 | alignment.py + Kiwi | CPU | CPU Worker |
| 언어 지표 계산 | metrics_pipeline.py | CPU | CPU Worker |
| RAG 문서 검색 | KURE-v1 임베딩 | CPU | CPU Worker |
| 리포트 생성 | EXAONE 2.4B | GPU | GPU Worker |
| RAG 문서 ingest | KURE-v1 임베딩 | CPU | CPU Worker (별도 큐) |

---

## 3. MVP 구성 — 2개 Worker 타입

### 3.1 CPU Worker

**역할**: 음성 전처리, VAD, 발화 정렬, 언어 지표, RAG 검색/ingest

```
담당 모델
├── Silero VAD (ONNX, ~2 MB)
├── KURE-v1 (sentence-transformers, ~500 MB)
└── Kiwi 형태소 분석기

EKS Node Group
├── 인스턴스: c5.xlarge (vCPU 4, 메모리 8 GB)
├── 오토스케일링: 최소 1 / 최대 5
└── 스팟 인스턴스 사용 가능
```

**Pod 리소스 설정 예시**

```yaml
resources:
  requests:
    cpu: "2"
    memory: "4Gi"
  limits:
    cpu: "4"
    memory: "8Gi"
```

---

### 3.2 GPU Worker

**역할**: pyannote 화자 분리, Whisper STT, EXAONE 리포트 생성

```
담당 모델
├── pyannote speaker-diarization-3.1 (~800 MB VRAM)
├── Whisper large-v3-turbo (~1.5 GB VRAM)
└── EXAONE-3.5-2.4B-Instruct (~5 GB VRAM)
합계: 약 7.3 GB VRAM (T4 16 GB 기준 여유 있음)

EKS Node Group
├── 인스턴스: g4dn.xlarge (T4 GPU 1장, VRAM 16 GB, vCPU 4, RAM 16 GB)
├── 오토스케일링: 최소 0 / 최대 3 (0으로 스케일인 가능)
└── 온디맨드 사용 권장 (스팟 인터럽트 시 분석 중단 위험)
```

**Pod 리소스 설정 예시**

```yaml
resources:
  requests:
    cpu: "2"
    memory: "8Gi"
    nvidia.com/gpu: "1"
  limits:
    cpu: "4"
    memory: "14Gi"
    nvidia.com/gpu: "1"
```

**Node 선택 강제 설정**

```yaml
nodeSelector:
  node.kubernetes.io/instance-type: g4dn.xlarge

tolerations:
  - key: "nvidia.com/gpu"
    operator: "Exists"
    effect: "NoSchedule"
```

---

## 4. SQS 큐 구성

```
utterai-cpu-analysis-queue   CPU Worker가 폴링 — VAD, 정렬, 지표, RAG 검색
utterai-gpu-analysis-queue   GPU Worker가 폴링 — Whisper, pyannote, EXAONE
utterai-rag-ingest-queue     CPU Worker가 폴링 — 문서 chunk + 임베딩 저장 (별도)
```

**권장 SQS 설정**

| 설정 | CPU 큐 | GPU 큐 |
|---|---|---|
| Visibility Timeout | 300초 (5분) | 1800초 (30분) |
| Message Retention | 4일 | 4일 |
| Long Polling | 20초 | 20초 |
| Dead Letter Queue | 재시도 3회 후 이동 | 재시도 2회 후 이동 |

GPU Worker는 모델 로드 시간 + 추론 시간을 합산해 Visibility Timeout을 넉넉히 설정합니다.

---

## 5. Job 처리 상세 흐름

```
[1단계 - CPU Worker]
SQS 메시지 수신 (job_id, session_id, s3_audio_key)
  → S3에서 음성 다운로드
  → ffmpeg 전처리 (16kHz mono WAV 변환)
  → Silero VAD → SpeechSegment 목록
  → RDS Job 상태 = PREPROCESSING_DONE
  → GPU 큐에 메시지 발행 (job_id, 전처리 음성 S3 key)

[2단계 - GPU Worker]
SQS 메시지 수신
  → pyannote 화자 분리 → SpeakerSegment 목록
  → Whisper STT → ASRResult
  → 결과를 S3에 임시 저장
  → RDS Job 상태 = TRANSCRIPTION_DONE
  → CPU 큐에 후처리 메시지 발행

[3단계 - CPU Worker]
SQS 메시지 수신
  → S3에서 SpeakerSegment + ASRResult 로드
  → alignment → Utterance 목록 (Kiwi 형태소 분석 포함)
  → metrics_pipeline → SpeakerMetrics 목록
  → RAG 검색 (LangGraph rag_graph.ainvoke)
  → GPU 큐에 리포트 생성 메시지 발행

[4단계 - GPU Worker]
SQS 메시지 수신
  → EXAONE 리포트 생성 (report_pipeline.generate_report)
  → ReportDraft → S3 저장 (JSON)
  → RDS Job 상태 = COMPLETED
  → RDS에 메타데이터 저장
```

---

## 6. 모델 로드 전략

GPU Worker는 모델을 Worker 시작 시 한 번만 로드하고 메모리에 유지합니다.
요청마다 로드하면 pyannote + Whisper + EXAONE 합산 약 1~2분이 소요됩니다.

```python
# GPU Worker 시작 시 (start_worker 진입점)
whisper_model.load()       # 모델을 메모리에 로드
pyannote_pipeline.load()
exaone_model.load()

# 이후 SQS 메시지 수신 시마다 predict()만 호출
while True:
    messages = sqs.receive_message(...)
    for msg in messages:
        handle_message(msg)
```

CPU Worker도 동일하게 시작 시 KURE-v1과 Kiwi를 로드합니다.

---

## 7. 오토스케일링 전략

### CPU Worker

SQS 큐의 메시지 수를 기반으로 KEDA(Kubernetes Event-Driven Autoscaler)를 사용합니다.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: cpu-worker-scaler
spec:
  scaleTargetRef:
    name: cpu-worker-deployment
  minReplicaCount: 1
  maxReplicaCount: 5
  triggers:
    - type: aws-sqs-queue
      metadata:
        queueURL: https://sqs.ap-northeast-2.amazonaws.com/.../utterai-cpu-analysis-queue
        queueLength: "3"    # Pod 1개당 처리 대기 메시지 수 목표
        awsRegion: ap-northeast-2
```

### GPU Worker

GPU 인스턴스는 비용이 크므로 메시지가 없을 때 0으로 스케일인합니다.

```yaml
minReplicaCount: 0      # 메시지 없으면 Pod 없음 (비용 절감)
maxReplicaCount: 3
triggers:
  - type: aws-sqs-queue
    metadata:
      queueLength: "1"  # GPU Pod 1개당 메시지 1개 목표
```

---

## 8. 인스턴스 비용 비교

| 인스턴스 | GPU | VRAM | 시간당 비용(서울) | 용도 |
|---|---|---|---|---|
| c5.xlarge | — | — | ~$0.19 | CPU Worker |
| g4dn.xlarge | T4 | 16 GB | ~$0.71 | GPU Worker (MVP) |
| g5.xlarge | A10G | 24 GB | ~$1.21 | GPU Worker (EXAONE 성능 개선 시) |
| g4dn.2xlarge | T4 | 16 GB | ~$1.42 | GPU Worker (동시 처리량 증가 시) |

GPU Worker를 KEDA로 0까지 스케일인하면 사용하지 않는 시간의 비용을 절감할 수 있습니다.

---

## 9. MVP → 운영 단계별 전환

### MVP (Dev 환경)

```
CPU Worker  1개 (c5.xlarge)
GPU Worker  1개 (g4dn.xlarge)
SQS 큐     3개
```

모델을 순차 처리하고 오토스케일링 없이 운영합니다.

### 운영 초기

```
CPU Worker  1~5개 (KEDA 오토스케일)
GPU Worker  0~3개 (KEDA 오토스케일, 0 스케일인 활성화)
Dead Letter Queue 모니터링 추가
CloudWatch 알람 설정
```

### 운영 고도화 (필요 시)

GPU Worker를 역할별로 추가 분리합니다.

```
Audio GPU Worker (pyannote + Whisper)  →  g4dn.xlarge
LLM GPU Worker   (EXAONE)              →  g5.xlarge
```

Whisper + pyannote는 짧은 음성 단위로 자주 실행되고,
EXAONE는 세션 1개당 1회만 실행되므로 스케일링 단위가 달라질 때 분리합니다.

---

## 10. 환경변수 Worker 타입별 분리

같은 Docker 이미지를 CPU/GPU Worker에 공통으로 사용하고
환경변수로 Worker 타입을 구분합니다.

```env
# CPU Worker Pod
WORKER_TYPE=cpu
MODEL_DEVICE=cpu
SQS_QUEUE_URL=https://sqs.../utterai-cpu-analysis-queue

# GPU Worker Pod
WORKER_TYPE=gpu
MODEL_DEVICE=cuda
ASR_DEVICE=cuda
LLM_DEVICE=cuda
SQS_QUEUE_URL=https://sqs.../utterai-gpu-analysis-queue
HF_TOKEN=hf_xxxxxxxx
```

Worker 시작 시 `WORKER_TYPE`을 읽어 로드할 모델과 폴링할 큐를 결정합니다.

```python
import os

WORKER_TYPE = os.getenv("WORKER_TYPE", "cpu")

if WORKER_TYPE == "gpu":
    whisper_model.load()
    pyannote_pipeline.load()
    exaone_model.load()
    start_gpu_worker()
else:
    vad_model.load()
    embedding_model.load()
    start_cpu_worker()
```
