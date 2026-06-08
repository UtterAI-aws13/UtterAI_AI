# EKS Worker 아키텍처

UtterAI AI 모듈의 EKS 기반 Worker 배포 구조를 설명합니다.

---

## 1. EKS 구조 기초

### 클러스터와 노드 그룹의 관계

EKS 클러스터는 쿠버네티스 컨트롤 플레인만 관리합니다.
실제로 컨테이너(Pod)가 돌아가는 서버는 클러스터에 붙은 **EC2 인스턴스(Node)**입니다.

```
EKS 클러스터 (utterai-cluster) — 1개 고정
  ├── Node Group: cpu-workers       (c5.xlarge EC2, 1~5대)
  ├── Node Group: ml-gpu-workers    (g4dn.xlarge EC2, 0~3대)
  └── Node Group: llm-gpu-workers   (g5.xlarge EC2, 0~2대)
```

- **클러스터는 늘리지 않습니다.** 오토스케일링은 노드 그룹 안의 **EC2 대수**가 늘었다 줄었다 하는 것입니다.
- 클러스터를 여러 개 띄우는 경우는 dev/staging/prod 환경 분리나 멀티 리전처럼 완전한 격리가 필요할 때입니다.
- EKS 기본 쿼터는 클러스터당 노드 그룹 30개지만 UtterAI 규모에서는 3개로 충분합니다.

---

## 2. 전체 구조 개요

```
Backend API
    │
    ├─ S3에 원본 음성 업로드
    └─ POST /internal/ai/analysis-jobs (AI FastAPI)
                   │
                   └─ SQS에 분석 요청 발행
           │
           ▼
  SQS: audio-preprocess-queue
           │
           ▼
    CPU Worker Pod
    (전처리, VAD, 정렬, 지표, RAG 검색)
           │
           │ 전처리 완료 → GPU 작업 위임
           ▼
  SQS: gpu-inference-queue
           │
           ▼
    ML GPU Worker Pod
    (pyannote 화자분리, Whisper STT)
           │
           │ transcript + speaker segments → S3 저장
           │ → report-analysis-queue 메시지 발행
           ▼
  SQS: report-analysis-queue
           │
           ▼
    LLM GPU Worker Pod
    (EXAONE 리포트 생성)
           │
           ▼
      S3 + RDS 저장
           │
           ▼
    Backend API 결과 조회
```

```
SQS: rag-ingest-queue  (별도 흐름)
           │
           ▼
    CPU Worker Pod
    (문서 chunk + KURE-v1 임베딩 + pgvector 저장)
```

---

## 3. ML Queue가 필요한 이유

CPU Worker는 c5.xlarge(GPU 없음)에서 실행됩니다.
pyannote와 Whisper는 GPU 없이는 실행할 수 없어 GPU Worker에게 위임해야 합니다.
그 전달 수단이 SQS 큐입니다.

| 대안 | 문제 |
|---|---|
| CPU Worker → GPU Worker HTTP 직접 호출 | CPU Worker가 GPU 처리 완료(~3분)까지 블로킹, 강한 결합 |
| 모든 단계를 GPU Worker에서 실행 | VAD·정렬·지표 같은 CPU 작업도 비싼 GPU 노드에서 실행 |

SQS 큐를 두면 CPU Worker는 메시지만 넣고 다음 Job을 처리하며,
GPU Worker는 독립적으로 스케일링됩니다.

---

## 4. Worker 분리 기준

| 단계 | 모델 | 리소스 | 담당 Worker |
|---|---|---|---|
| 음성 전처리 (ffmpeg) | — | CPU | CPU Worker |
| VAD 말소리 감지 | Silero VAD (ONNX) | CPU | CPU Worker |
| 화자 분리 | pyannote 3.1 | GPU | ML GPU Worker |
| STT 전사 | Whisper large-v3-turbo | GPU | ML GPU Worker |
| 발화 정렬 | alignment.py + Kiwi | CPU | CPU Worker |
| 언어 지표 계산 | metrics_pipeline.py | CPU | CPU Worker |
| RAG 문서 검색 | KURE-v1 임베딩 | CPU | CPU Worker |
| 리포트 생성 | EXAONE 2.4B | GPU | LLM GPU Worker |
| RAG 문서 ingest | KURE-v1 임베딩 | CPU | CPU Worker (별도 큐) |

---

## 5. Worker 상세

### 5.1 CPU Worker

**역할**: 음성 전처리, VAD, 발화 정렬, 언어 지표, RAG 검색/ingest

```
담당 모델
├── Silero VAD (ONNX, ~2 MB)
├── KURE-v1 (sentence-transformers, ~500 MB)
└── Kiwi 형태소 분석기

EKS Node Group
├── 인스턴스: c5.xlarge (vCPU 4, RAM 8 GB)
├── 오토스케일링: 최소 1 / 최대 5
└── 스팟 인스턴스 사용 가능
```

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

### 5.2 ML GPU Worker

**역할**: pyannote 화자 분리, Whisper STT

```
담당 모델
├── pyannote speaker-diarization-3.1 (~800 MB VRAM)
└── Whisper large-v3-turbo (~1.5 GB VRAM)
합계: ~2.3 GB VRAM (T4 16 GB 기준 여유 있음)

EKS Node Group
├── 인스턴스: g4dn.xlarge (T4 GPU 1장, VRAM 16 GB, vCPU 4, RAM 16 GB)
├── 오토스케일링: 최소 0 / 최대 3
└── 스팟 인스턴스 사용 가능 (SQS 재시도로 복구)
```

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

nodeSelector:
  node.kubernetes.io/instance-type: g4dn.xlarge

tolerations:
  - key: "nvidia.com/gpu"
    operator: "Exists"
    effect: "NoSchedule"
```

---

### 5.3 LLM GPU Worker

**역할**: EXAONE 리포트 생성

```
담당 모델
└── EXAONE-3.5-2.4B-Instruct (~5 GB VRAM, bfloat16 기준)

EKS Node Group
├── 인스턴스: g5.xlarge (A10G GPU 1장, VRAM 24 GB, vCPU 4, RAM 16 GB)
├── 오토스케일링: 최소 0 / 최대 2
└── 온디맨드 1대 기본 + 트래픽 증가 시 스팟 추가 권장
```

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

nodeSelector:
  node.kubernetes.io/instance-type: g5.xlarge
```

---

## 6. GPU 인스턴스 선택 기준

### ML GPU Worker에 T4(g4dn), LLM GPU Worker에 A10G(g5)를 쓰는 이유

pyannote와 Whisper는 **인코더 기반 추론**입니다.
입력 전체를 병렬로 처리하므로 Tensor Core 연산량이 병목이고 T4로 충분합니다.

EXAONE은 **autoregressive 생성** 방식입니다.
토큰 1개를 생성할 때마다 모델 전체 가중치(~5 GB)를 메모리에서 읽어야 합니다.

```
토큰 1 생성 → 5 GB 가중치 읽기
토큰 2 생성 → 5 GB 가중치 읽기
...
512 토큰까지 반복
```

이 구조에서는 **메모리 대역폭이 곧 생성 속도**입니다.

| 항목 | T4 (g4dn) | A10G (g5) |
|---|---|---|
| VRAM | 16 GB | 24 GB |
| 메모리 대역폭 | 300 GB/s | 600 GB/s |
| Tensor Core 세대 | Turing (2세대) | Ampere (3세대) |
| EXAONE 토큰 생성 속도 | ~20 tok/s | ~40 tok/s |
| 512 토큰 생성 시간 | ~26초 | ~13초 |
| 시간당 비용 (서울) | ~$0.53 | ~$1.21 |

T4에서 EXAONE을 돌릴 수는 있지만, LLM은 구조적으로 메모리 대역폭에 묶여 있어 A10G에서 빠르게 끝내고 0 scale-in하는 편이 **처리량과 비용 모두 유리**합니다.

---

## 7. SQS 큐 구성

```
utterai-audio-preprocess-queue   CPU Worker 폴링 — VAD, 정렬, 지표, RAG 검색
utterai-gpu-inference-queue       ML GPU Worker 폴링 — pyannote, Whisper
utterai-report-analysis-queue            LLM GPU Worker 폴링 — EXAONE 리포트 생성
utterai-rag-ingest-queue     CPU Worker 폴링 — 문서 chunk + 임베딩 저장 (별도)
```

**권장 SQS 설정**

| 설정 | CPU 큐 | ML GPU 큐 | LLM 큐 |
|---|---|---|---|
| Visibility Timeout | 300초 | 600초 | 1800초 |
| Message Retention | 4일 | 4일 | 4일 |
| Long Polling | 20초 | 20초 | 20초 |
| Dead Letter Queue | 재시도 3회 | 재시도 2회 | 재시도 2회 |

---

## 8. Job 처리 상세 흐름

```
[1단계 - CPU Worker]
SQS 메시지 수신 (job_id, session_id, s3_audio_key)
  → S3에서 음성 다운로드
  → ffmpeg 전처리 (16kHz mono WAV 변환)
  → Silero VAD → SpeechSegment 목록
  → RDS Job 상태 = PREPROCESSING_DONE
  → gpu-inference-queue에 메시지 발행 (job_id, 전처리 음성 S3 key)

[2단계 - ML GPU Worker]
SQS 메시지 수신
  → pyannote 화자 분리 → SpeakerSegment 목록
  → Whisper STT → ASRResult
  → S3에 중간 결과 저장 (speaker_segments.json, asr_result.json)
  → RDS Job 상태 = TRANSCRIPTION_DONE
  → report-analysis-queue에 메시지 발행 (job_id, 중간 결과 S3 key)

[3단계 - LLM GPU Worker]
SQS 메시지 수신
  → S3에서 SpeakerSegment + ASRResult 로드
  → alignment → Utterance 목록 (Kiwi 형태소 분석 포함)
  → metrics_pipeline → SpeakerMetrics 목록
  → RAG 검색 (LangGraph rag_graph.ainvoke)
  → EXAONE 리포트 생성 (report_pipeline.generate_report)
  → ReportDraft → S3 저장 (JSON)
  → RDS Job 상태 = COMPLETED
```

---

## 9. 모델 로드 전략

Worker는 모델을 시작 시 한 번만 로드하고 메모리에 유지합니다.
Job마다 로드하면 pyannote + Whisper + EXAONE 합산 cold start가 60~90초 소요됩니다.

```python
# GPU Worker 시작 시 1회만 실행
def startup():
    pyannote_pipeline.load()
    whisper_model.load()      # ML GPU Worker
    exaone_model.load()       # LLM GPU Worker

# 이후 SQS 메시지마다 predict()만 호출
while True:
    messages = sqs.receive_message(...)
    for msg in messages:
        handle_message(msg)
```

CPU Worker도 동일하게 시작 시 KURE-v1과 Kiwi를 로드합니다.

---

## 10. 오토스케일링 전략 (KEDA)

### CPU Worker

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
        queueURL: https://sqs.ap-northeast-2.amazonaws.com/.../utterai-audio-preprocess-queue
        queueLength: "3"
        awsRegion: ap-northeast-2
```

### ML GPU Worker

```yaml
minReplicaCount: 0      # 메시지 없으면 Pod 없음
maxReplicaCount: 3
triggers:
  - type: aws-sqs-queue
    metadata:
      queueURL: https://sqs.ap-northeast-2.amazonaws.com/.../utterai-gpu-inference-queue
      queueLength: "1"
```

### LLM GPU Worker

```yaml
minReplicaCount: 0
maxReplicaCount: 2
triggers:
  - type: aws-sqs-queue
    metadata:
      queueURL: https://sqs.ap-northeast-2.amazonaws.com/.../utterai-report-analysis-queue
      queueLength: "1"
```

---

## 11. 스팟 인스턴스 전략

### 할인율

서울 리전 기준 온디맨드 대비 60~70% 저렴합니다.

| 인스턴스 | 온디맨드 | 스팟 | 절감 |
|---|---|---|---|
| c5.xlarge | $0.19/h | ~$0.06/h | 68% |
| g4dn.xlarge | $0.53/h | ~$0.16/h | 70% |
| g5.xlarge | $1.21/h | ~$0.40/h | 67% |

가격 최신 확인: `aws.amazon.com/ec2/pricing/on-demand/` → Region: Asia Pacific (Seoul)

### 스팟 인터럽션 발생 시 복구 흐름

AWS가 2분 예고 후 인스턴스를 회수하면 처리 중인 Job이 종료됩니다.
UtterAI는 SQS 기반 비동기 처리라 자동 복구됩니다.

```
Worker 인스턴스 회수
  → SQS visibility timeout 만료
  → 메시지가 큐에 다시 노출
  → 다른 Worker(또는 재시작된 Worker)가 동일 Job 재처리
  → 사용자: 분석이 예상보다 조금 더 걸림
```

분석 결과를 실시간으로 기다리는 구조가 아닌 **완료 알림을 받는 비동기 구조**라 인터럽션이 치명적이지 않습니다.

### Worker별 스팟 적용 판단

| Worker | 스팟 적용 | 판단 이유 |
|---|---|---|
| CPU Worker | **가능** | Job이 빠르고(수 초~1분), SQS 재시도로 복구 |
| ML GPU Worker | **가능** | pyannote + Whisper 합산 ~3분, 인터럽션 시 처음부터 재처리하지만 SQS가 보장 |
| LLM GPU Worker | **온디맨드 1대 기본 + 스팟 추가** | 앞 단계 결과가 S3에 저장된 뒤라 재처리 비용은 낮지만, 가용성이 낮을 때 report-analysis-queue가 막힐 수 있음 |

### 권장 조합

```
CPU Worker      → 스팟
ML GPU Worker   → 스팟
LLM GPU Worker  → 온디맨드 최소 1대 + 트래픽 증가 시 스팟 추가
RDS             → 스팟 미지원 (온디맨드)
```

---

## 12. 비용 추정

### 규모별 월 비용 (온디맨드 기준, KEDA 0 scale-in 적용)

치료사 20명, 1인 하루 3세션, 세션당 GPU 처리 3분 가정.

```
하루 GPU 가동 시간 = 20명 × 3세션 × 3분 = 180분 = 3시간
월 GPU 가동 시간  = 3시간 × 22일(업무일) = 66시간
```

| 항목 | 사양 | 월 가동 | 온디맨드 | 스팟 적용 |
|---|---|---|---|---|
| CPU Worker | c5.xlarge × 1 (상시) | 720h | $137 | $43 |
| ML GPU Worker | g4dn.xlarge (세션 때만) | 66h | $35 | $11 |
| LLM GPU Worker | g5.xlarge (세션 때만) | 66h | $80 | $26 |
| RDS | db.t3.medium (상시) | 720h | $49 | $49 |
| **합계** | | | **$301** | **$129** |

스팟 적용 시 월 **$129**, 온디맨드 대비 **57% 절감**.

### 규모별 빠른 추산

| 규모 | 치료사 수 | GPU 가동률 | 월 비용 (스팟 기준) |
|---|---|---|---|
| MVP | ~20명 | ~10% | ~$130 |
| 초기 운영 | ~100명 | ~30% | ~$280 |
| 성장기 | ~500명 | ~70% | ~$700 |

GPU Worker를 0 scale-in 없이 **상시 켜두면** g4dn + g5 합산 월 ~$540(스팟 기준)이 고정으로 나옵니다.
KEDA 0 scale-in이 비용에서 가장 효과가 큽니다.

---

## 13. MVP → 운영 단계별 전환

### MVP (Dev 환경)

```
CPU Worker      1개 (c5.xlarge, 온디맨드)
ML GPU Worker   1개 (g4dn.xlarge, 온디맨드)
LLM GPU Worker  1개 (g5.xlarge, 온디맨드)
SQS 큐          4개
```

모델을 순차 처리하고 오토스케일링 없이 운영합니다.

### 운영 초기

```
CPU Worker      1~5개 (KEDA, 스팟)
ML GPU Worker   0~3개 (KEDA, 스팟, 0 scale-in 활성화)
LLM GPU Worker  0~2개 (KEDA, 온디맨드 1대 기본 + 스팟 추가)
Dead Letter Queue 모니터링 추가
CloudWatch 알람 설정
```

### 운영 고도화 (필요 시)

ML Worker를 음성 길이 기준으로 세분화합니다.

```
짧은 음성 (< 5분) ML Worker   → g4dn.xlarge 스팟
긴 음성 (>= 5분)  ML Worker   → g4dn.2xlarge 스팟 (vCPU 8)
LLM Worker                    → g5.xlarge 온디맨드
```

---

## 14. 환경변수 Worker 타입별 분리

같은 Docker 이미지를 CPU/ML GPU/LLM GPU Worker에 공통으로 사용하고
환경변수로 Worker 타입을 구분합니다.

```env
# CPU Worker Pod
WORKER_TYPE=cpu
MODEL_DEVICE=cpu
SQS_QUEUE_URL=https://sqs.../utterai-audio-preprocess-queue

# ML GPU Worker Pod
WORKER_TYPE=ml-gpu
MODEL_DEVICE=cuda
ASR_DEVICE=cuda
SQS_QUEUE_URL=https://sqs.../utterai-gpu-inference-queue
HF_TOKEN=hf_xxxxxxxx

# LLM GPU Worker Pod
WORKER_TYPE=llm-gpu
MODEL_DEVICE=cuda
LLM_DEVICE=cuda
SQS_QUEUE_URL=https://sqs.../utterai-report-analysis-queue
HF_TOKEN=hf_xxxxxxxx
```

```python
import os

WORKER_TYPE = os.getenv("WORKER_TYPE", "cpu")

if WORKER_TYPE == "ml-gpu":
    pyannote_pipeline.load()
    whisper_model.load()
    start_ml_gpu_worker()
elif WORKER_TYPE == "llm-gpu":
    exaone_model.load()
    start_llm_gpu_worker()
else:
    vad_model.load()
    embedding_model.load()
    start_cpu_worker()
```
