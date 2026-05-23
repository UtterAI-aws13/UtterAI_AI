## UtterAI AI Module

---

### 진행 상황

#### 완료
- [x] 레포 구조 생성 및 기본 설정 파일 (`Dockerfile`, `requirements.txt`, `.env.example`)
- [x] 설계 문서 작성 (`docs/AI_IMPLEMENTATION_GUIDE.md`)
- [x] 공통 Schema 정의 (`schemas/job`, `audio`, `segment`, `transcript`, `metrics`, `rag`, `report`)
- [x] 모델 Wrapper 스켈레톤 (`vad_silero`, `asr_whisper`, `diarization_pyannote`, `embedding_kure`, `llm_exaone`)
- [x] 파이프라인 스켈레톤 (`audio_preprocess`, `alignment`, `metrics_pipeline`, `report_pipeline`, `analysis_pipeline`)
- [x] 언어 지표 계산 로직 구현 (`metrics/mlu`, `lexical_diversity`, `response_latency`)
- [x] RAG 도메인 개념 사전 (`rag/ontology.yaml`)
- [x] RAG Semantic Layer 구현 (`rag/semantic_layer.py` — 쿼리 확장 + 메타데이터 필터)
- [x] EXAONE 프롬프트 빌더 구현 (`rag/prompt_templates.py`)
- [x] API 스켈레톤 (`api/health`, `jobs`, `rag`)
- [x] Worker 스켈레톤 (`workers/analysis_worker`, `rag_ingest_worker`)
- [x] Storage 스켈레톤 (`storage/s3_client`, `db`)

#### 진행 예정 (구현 순서)
- [ ] **3단계** VAD 단독 실행 — `app/models/vad_silero.py` `load` / `predict` 구현
- [ ] **4단계** Whisper 단독 실행 — `app/models/asr_whisper.py` `load` / `predict` 구현
- [ ] **5단계** pyannote 단독 실행 — `app/models/diarization_pyannote.py` `load` / `predict` 구현
- [ ] **6단계** 발화 정렬 — `app/pipelines/alignment.py` `align_segments` 구현
- [ ] **7단계** metrics_pipeline 연결 — `app/pipelines/metrics_pipeline.py` 구현 (개별 계산 함수는 완료)
- [ ] **8단계** RAG ingest — `app/rag/ingest.py`, `chunker.py`, `vector_store.py` 구현
- [ ] **9단계** RAG query — `app/rag/retriever.py` vector_store 연결
- [ ] **10단계** LLM 리포트 생성 — `app/pipelines/report_pipeline.py` 구현
- [ ] **11단계** Worker 통합 — `app/workers/analysis_worker.py` SQS 폴링 루프 구현
- [ ] **12단계** Docker 빌드 검증 — 이미지 빌드 및 로컬 실행 확인

---

### 1. 문서 목적

이 문서는 `Utter_AI` 레포지토리에서 **AI 모델 처리, 음성 분석 파이프라인, RAG 기반 리포트 생성**을 구현하기 위한 기본 README입니다.

`Utter_AI` 레포는 전체 서비스 중에서 다음 영역만 담당합니다.

| 구분 | 담당 여부 | 설명 |
| --- | --- | --- |
| 음성 업로드 화면 | 제외 | `UtterAI_FE` 담당 |
| 사용자/세션 API | 제외 | `UtterAI_BE` 담당 |
| AI 모델 추론 | 포함 | VAD, 화자 분리, STT, 임베딩, LLM |
| 언어 지표 계산 | 포함 | MLU, NDW, NTW, TTR, 반응 지연 시간 |
| RAG 검색 | 포함 | 언어발달/치료 문서 검색, 근거 추출 |
| SOAP Note 초안 생성 | 포함 | 검색 근거 기반 LLM 리포트 초안 생성 |
| 인프라 배포 정의 | 제외 | `UtterAI_Infra` 담당 |

현재 MVP 단계에서는 **모델을 새로 학습하거나 파인튜닝하지 않고**, Hugging Face에 공개된 모델을 가져와 추론 파이프라인에 연결하는 것을 우선 목표로 합니다.

---

### 2. AI 모듈의 역할

UtterAI의 AI 모듈은 언어치료 세션 음성을 입력받아 다음 결과를 생성합니다.

```text
원본 음성
  -> 말한 구간 감지
  -> 화자 분리
  -> STT 전사
  -> 발화 단위 정리
  -> 언어 지표 계산
  -> 관련 문서 RAG 검색
  -> SOAP Note / 분석 리포트 초안 생성
  -> 치료사 검토용 결과 반환
```

최종 결과는 **치료사를 대체하는 자동 진단 결과**가 아니라, 치료사가 검토하고 수정할 수 있는 **임상 업무 보조 초안**입니다.

---

### 3. 확정 AI 모델 구성

| 단계 | 사용 모델/라이브러리 | 실행 위치 | 역할 |
| --- | --- | --- | --- |
| VAD | `onnx-community/silero-vad` | CPU Worker | 음성에서 말한 구간과 침묵 구간 분리 |
| 화자 분리 | `pyannote/speaker-diarization-3.1` | GPU Worker 권장 | 치료사/아동/보호자 등 화자별 발화 구간 분리 |
| STT/ASR | `openai/whisper-large-v3-turbo` | GPU Worker 권장 | 음성을 텍스트로 전사 |
| 형태소/키워드 분석 | `kiwipiepy` 기반 Kiwi | CPU Worker | 한국어 형태소 분석, 키워드 추출, RAG 질의 확장 |
| 임베딩 | `nlpai-lab/KURE-v1` | CPU 또는 GPU Worker | 한국어 문서/질의 임베딩 생성 |
| 리포트 생성 LLM | `LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct` | GPU Worker 권장 | RAG 근거 기반 SOAP Note 초안 생성 |
| 언어 지표 계산 | Python 계산 로직 | CPU Worker | MLU, NDW, NTW, TTR, 반응 지연 시간 계산 |

---

### 4. 전체 처리 흐름

```mermaid
flowchart LR
    A[Backend에서 분석 Job 생성] --> B[S3 원본 음성 저장]
    B --> C[SQS 분석 요청 메시지]
    C --> D[AI Worker Job 수신]
    D --> E[VAD 말한 구간 감지]
    E --> F[화자 분리]
    F --> G[Whisper STT]
    G --> H[발화 단위 정렬]
    H --> I[언어 지표 계산]
    I --> J[RAG 문서 검색]
    J --> K[LLM 리포트 초안 생성]
    K --> L[S3 결과 JSON/리포트 저장]
    L --> M[RDS 메타데이터 저장]
    M --> N[Backend에서 결과 조회]
```

---

### 5. 저장소 역할 분리

AI 모듈에서 생성하는 데이터는 S3와 RDS에 나누어 저장합니다.

| 저장 위치 | 저장 대상 | 이유 |
| --- | --- | --- |
| S3 | 원본 음성 파일 | 파일 크기가 크고 객체 저장에 적합 |
| S3 | 전처리된 음성/세그먼트 음성 | 추후 재분석, 디버깅, 모델 개선용 |
| S3 | transcript JSON | 긴 전사 결과를 파일 형태로 보관 |
| S3 | report JSON / PDF / Markdown | 결과 리포트 파일 저장 |
| S3 | RAG 원본 문서 | 기관 자료, 가이드라인, 치료 문서 보관 |
| RDS PostgreSQL | 사용자/세션 메타데이터 | 서비스 조회와 관계형 관리 |
| RDS PostgreSQL | 오디오 파일 메타데이터 | S3 key, duration, format, status |
| RDS PostgreSQL | 화자/발화 메타데이터 | speaker_id, start_time, end_time |
| RDS PostgreSQL | 언어 지표 | MLU, NDW, NTW, TTR 등 숫자 결과 |
| RDS PostgreSQL | 리포트 상태 | 생성 중, 완료, 실패, 치료사 승인 여부 |
| RDS PostgreSQL + pgvector | RAG chunk 임베딩 | 문서 검색을 위한 벡터 검색 |

---

### 6. 권장 레포 구조

```text
Utter_AI/
├── README.md
├── docs/
│   └── AI_IMPLEMENTATION_GUIDE.md
├── app/
│   ├── main.py
│   ├── config.py
│   ├── api/
│   │   ├── health.py
│   │   ├── jobs.py
│   │   └── rag.py
│   ├── schemas/
│   │   ├── job.py
│   │   ├── transcript.py
│   │   ├── metrics.py
│   │   └── report.py
│   ├── models/
│   │   ├── vad_silero.py
│   │   ├── diarization_pyannote.py
│   │   ├── asr_whisper.py
│   │   ├── embedding_kure.py
│   │   └── llm_exaone.py
│   ├── pipelines/
│   │   ├── audio_pipeline.py
│   │   ├── transcript_pipeline.py
│   │   ├── metric_pipeline.py
│   │   └── report_pipeline.py
│   ├── rag/
│   │   ├── ingest.py
│   │   ├── chunker.py
│   │   ├── retriever.py
│   │   ├── semantic_layer.py
│   │   ├── ontology.yaml
│   │   └── prompt_templates.py
│   ├── metrics/
│   │   ├── mlu.py
│   │   ├── lexical.py
│   │   └── latency.py
│   ├── workers/
│   │   ├── analysis_worker.py
│   │   └── rag_ingest_worker.py
│   └── storage/
│       ├── s3_client.py
│       ├── db.py
│       └── repositories.py
├── tests/
│   ├── unit/
│   └── integration/
├── scripts/
│   ├── run_local_api.sh
│   ├── run_worker.sh
│   └── ingest_rag_docs.sh
├── Dockerfile
├── requirements.txt
├── .env.example
└── pyproject.toml
```

---

### 7. 로컬 실행 흐름

#### 7.1 Python 환경 준비

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### 7.2 환경 변수 설정

`.env.example`을 복사해서 `.env`를 만듭니다.

```bash
cp .env.example .env
```

필수 환경 변수 예시는 다음과 같습니다.

```env
APP_ENV=local
LOG_LEVEL=INFO

HF_TOKEN=your_huggingface_token

S3_BUCKET_UTTERAI_AUDIO=utterai-audio-dev
S3_BUCKET_UTTERAI_REPORT=utterai-report-dev
S3_BUCKET_UTTERAI_RAG=utterai-rag-dev

DATABASE_URL=postgresql+psycopg://utterai:utterai@localhost:5432/utterai_ai

VECTOR_DB_PROVIDER=pgvector
EMBEDDING_MODEL_NAME=nlpai-lab/KURE-v1
LLM_MODEL_NAME=LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct

VAD_MODEL_NAME=onnx-community/silero-vad
DIARIZATION_MODEL_NAME=pyannote/speaker-diarization-3.1
ASR_MODEL_NAME=openai/whisper-large-v3-turbo
```

`pyannote` 계열 모델은 Hugging Face 토큰과 모델 접근 권한이 필요할 수 있습니다.

---

### 8. API 실행

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

헬스 체크:

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

---

### 9. Worker 실행

분석 Worker는 SQS 메시지를 받아 비동기 분석을 수행하는 구조를 기본으로 합니다.

```bash
python -m app.workers.analysis_worker
```

로컬 개발 단계에서는 SQS 없이 파일 경로를 직접 넘겨 테스트할 수 있습니다.

```bash
python -m app.pipelines.audio_pipeline \
  --session-id local-session-001 \
  --audio-path ./samples/session_001.wav
```

---

### 10. 핵심 API 초안

| Method | Path | 설명 |
| --- | --- | --- |
| `GET` | `/health/live` | 프로세스 생존 확인 |
| `GET` | `/health/ready` | 모델/DB/S3 연결 준비 상태 확인 |
| `POST` | `/ai/jobs` | 분석 Job 생성 요청 |
| `GET` | `/ai/jobs/{job_id}` | 분석 Job 상태 조회 |
| `POST` | `/ai/rag/ingest` | RAG 문서 수집/청크/임베딩 |
| `POST` | `/ai/rag/query` | RAG 검색 테스트 |
| `POST` | `/ai/reports/draft` | RAG 기반 리포트 초안 생성 |

---

### 11. MVP 구현 범위

#### 11.1 MVP에 포함

- S3에 있는 음성 파일을 읽어서 분석
- Silero VAD로 말한 구간 추출
- pyannote로 화자 분리
- Whisper로 STT 전사
- 화자별 발화 단위 정리
- MLU, NDW, NTW, TTR, 반응 지연 시간 계산
- RAG 문서 업로드, 청크, 임베딩, 검색
- RAG 검색 결과 기반 SOAP Note 초안 JSON 생성
- 분석 결과를 S3와 RDS에 저장
- FastAPI 기반 테스트 API 제공
- Docker 이미지 빌드 가능 상태 구성

#### 11.2 MVP에서 제외

- 모델 파인튜닝
- 자동 진단 확정
- 의료적 판단 자동화
- 복잡한 실시간 스트리밍 처리
- 완전한 멀티 리전 운영
- EKS GPU Node Group 운영 자동화

MVP에서는 **작동하는 분석 파이프라인**을 먼저 만들고, 이후 성능과 인프라를 확장합니다.

---

### 12. 배포 방향

초기에는 다음 구조를 목표로 합니다.

```text
Backend API
  -> S3에 원본 음성 업로드
  -> SQS에 분석 요청 발행
  -> AI Worker가 Job 처리
  -> S3/RDS에 결과 저장
  -> Backend API가 결과 조회
```

배포 단계별 방향은 다음과 같습니다.

| 단계 | 실행 방식 | 설명 |
| --- | --- | --- |
| Local | FastAPI + 로컬 Worker | 모델 연동과 파이프라인 검증 |
| Dev | Docker + ECS Fargate CPU Worker | VAD, Kiwi, RAG 검색, 메트릭 계산 중심 |
| GPU 확장 | EKS GPU Node Group 또는 GPU EC2 Worker | Whisper, pyannote, EXAONE 처리 |
| 운영 고도화 | SQS + Step Functions + CloudWatch | 비동기 작업 추적, 재시도, 장애 관찰 |

---

### 13. 개발 우선순위

| 순서 | 작업 | 목표 |
| --- | --- | --- |
| 1 | 레포 구조 생성 | AI 코드 영역 분리 |
| 2 | 공통 설정/스키마 작성 | Job, Transcript, Metric, Report 계약 정의 |
| 3 | VAD 단독 실행 | 음성 구간 추출 검증 |
| 4 | Whisper 단독 실행 | STT 결과 JSON 생성 |
| 5 | pyannote 단독 실행 | speaker segment 결과 생성 |
| 6 | 발화 정렬 로직 구현 | speaker + transcript 병합 |
| 7 | 언어 지표 계산 | MLU, NDW, NTW, TTR 산출 |
| 8 | RAG 문서 ingest | chunk + embedding + pgvector 저장 |
| 9 | RAG 검색 API | 질의 기반 근거 검색 |
| 10 | LLM 리포트 생성 | SOAP Note 초안 JSON 생성 |
| 11 | Worker 통합 | SQS 기반 비동기 처리 |
| 12 | Docker화 | 배포 가능한 이미지 생성 |

---

### 14. 결과물 예시

AI 모듈의 최종 출력은 다음과 같은 구조를 목표로 합니다.

```json
{
  "job_id": "job_001",
  "session_id": "session_001",
  "status": "COMPLETED",
  "transcript": {
    "utterances": [
      {
        "speaker": "CHILD",
        "start_time": 1.25,
        "end_time": 3.10,
        "text": "엄마 이거 봐",
        "confidence": 0.91
      }
    ]
  },
  "metrics": {
    "mlu": 3.8,
    "ntw": 142,
    "ndw": 76,
    "ttr": 0.535,
    "average_response_latency_sec": 1.42
  },
  "rag_evidence": [
    {
      "document_id": "doc_001",
      "title": "언어발달 평가 가이드",
      "chunk_id": "chunk_014",
      "score": 0.82
    }
  ],
  "report": {
    "soap_note": {
      "subjective": "...",
      "objective": "...",
      "assessment": "...",
      "plan": "..."
    },
    "review_required": true
  }
}
```

---

### 15. 운영 원칙

- 원본 음성, 전사 결과, 리포트는 민감 데이터로 취급합니다.
- 로그에는 원문 음성, 전체 전사문, 개인정보를 남기지 않습니다.
- 모델 출력은 반드시 치료사 검토 대상으로 표시합니다.
- RAG 답변은 검색된 근거 문서 안에서만 생성합니다.
- 모델 버전, 프롬프트 버전, RAG 문서 버전은 결과와 함께 기록합니다.
- 오류 발생 시 Job 상태를 `FAILED`로 저장하고 재시도 가능하게 설계합니다.

---

### 16. 관련 상세 문서

자세한 구현 방식은 다음 문서를 참고합니다.

```text
docs/AI_IMPLEMENTATION_GUIDE.md
```
