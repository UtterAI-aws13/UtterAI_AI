# UtterAI_AI

언어치료 세션 음성을 분석해 SOAP Note 초안을 생성하는 AI 파이프라인 서비스.

## 역할 범위

| 담당 | 비담당 |
|---|---|
| 음성 전처리 / VAD / 화자 분리 / STT | 사용자·세션 API (`UtterAI_BE`) |
| 언어 지표 계산 (MLU, NDW, NTW, TTR, 반응 지연) | 프론트엔드 (`UtterAI_FE`) |
| RAG 문서 검색 (pgvector + LangGraph) | 인프라 배포 정의 (`UtterAI_Infra`) |
| SOAP Note 초안 생성 (AWS Bedrock) | |
| SQS 기반 3단계 비동기 파이프라인 | |

## 처리 흐름

```
원본 음성
  → [CPU Worker]      전처리(ffmpeg) + VAD(Silero) → S3(WAV, VAD JSON)
  → [ML GPU Worker]   화자 분리(pyannote) + STT(Whisper) + 정렬(alignment)
                      → transcript draft S3 저장 + RDS(transcripts, transcript_segments) 저장
                      → analysis_jobs.status = COMPLETED
  → [LLM GPU Worker]  지표 계산 + RAG 검색 + SOAP Note 생성(Bedrock/EXAONE)
                      → S3(report JSON)
```

각 단계는 SQS 큐로 연결된 독립 Worker Pod로 실행됩니다.

> **단계별 책임 요약**
> - CPU Worker: 전처리 + VAD → `SQS GPU Inference Queue` 발행
> - ML GPU Worker: 화자분리 + ASR + **alignment + transcript draft 저장(S3+RDS)** → `analysis_jobs.status=COMPLETED`
> - LLM GPU Worker: 지표 계산 + RAG + 리포트 생성 → S3 저장 (별도 흐름, transcript와 독립)

## AI 모델 구성

| 단계 | 모델 | Worker | 비고 |
|---|---|---|---|
| VAD | `onnx-community/silero-vad` | CPU | ONNX 추론 |
| 화자 분리 | `pyannote/speaker-diarization-3.1` | ML GPU | HF_TOKEN 필요 |
| STT | `openai/whisper-large-v3-turbo` | ML GPU | |
| 형태소 분석 | `kiwipiepy` | CPU | RAG 키워드 추출 |
| 임베딩 | `nlpai-lab/KURE-v1` | CPU | 1024차원 |
| 리포트 생성 | AWS Bedrock Claude Haiku | LLM GPU | `bedrock_client.py` |
| LLM (로컬 대안) | `LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct` | LLM GPU | `llm_exaone.py` |

> 현재 운영 파이프라인은 Bedrock Claude를 사용합니다. EXAONE은 로컬/오프라인 대안으로 유지합니다.

## 폴더 구조

```
app/
├── config.py          환경 변수 로드 (pydantic-settings)
├── main.py            FastAPI 앱 (health, jobs, rag 라우터)
├── schemas/           서비스 전반 데이터 계약 정의
├── models/            AI 모델 래퍼 (load → predict 패턴)
├── pipelines/         단계별 오케스트레이터
│   ├── analysis_pipeline.py   3단계 파이프라인 (CPU/ML GPU/LLM GPU)
│   ├── audio_preprocess.py    ffmpeg 전처리
│   ├── alignment.py           VAD+화자분리+ASR 정렬 → Utterance
│   ├── metrics_pipeline.py    언어 지표 계산
│   ├── report_pipeline.py     Bedrock/EXAONE SOAP Note 생성
│   └── bedrock_client.py      AWS Bedrock 호출 클라이언트
├── metrics/           언어 지표 순수 함수 (mlu, lexical_diversity, response_latency)
├── rag/               RAG 파이프라인 (ingest → pgvector, LangGraph query)
├── api/               FastAPI 라우터 (health, jobs, rag)
├── workers/           SQS 폴링 Worker (cpu, ml_gpu, llm_gpu, rag_ingest)
├── storage/           S3 클라이언트, PostgreSQL async 연결
├── mocks/             로컬 테스트용 mock 데이터
└── utils/             오디오 유틸, ID 생성 유틸
```

## 환경 변수

`.env.example` 참고. 주요 항목:

| 변수 | 설명 |
|---|---|
| `HF_TOKEN` | Hugging Face 토큰 (pyannote gated model 필수) |
| `AWS_REGION` | AWS 리전 |
| `S3_BUCKET_AUDIO` | 오디오 버킷 |
| `S3_BUCKET_REPORT` | 결과 리포트 버킷 |
| `DB_*` | PostgreSQL(pgvector) 접속 정보 |
| `SQS_AUDIO_PREPROCESS_QUEUE_URL` | CPU Worker 입력 큐 |
| `SQS_GPU_INFERENCE_QUEUE_URL` | ML GPU Worker 입력 큐 |
| `SQS_REPORT_ANALYSIS_QUEUE_URL` | LLM GPU Worker 입력 큐 |
| `BEDROCK_REPORT_MODEL_ID` | Bedrock 모델 ID |
| `WORKER_TYPE` | Pod에서 주입 (`cpu` / `ml-gpu` / `llm-gpu`) |

## 로컬 실행

```bash
# 1. 가상환경 설정 (uv 사용)
python -m venv .venv
.venv\Scripts\activate      # Windows
source .venv/bin/activate   # macOS / Linux

pip install uv
uv pip install -e ".[cpu,dev]"   # CPU 환경
# uv pip install -e ".[gpu,dev]"  # GPU 환경

# 2. 환경 파일 설정
cp .env.example .env  # HF_TOKEN 등 입력

# 3. PostgreSQL + pgvector 실행
docker compose up -d
python scripts/create_tables.py  # 최초 1회

# 4. FastAPI 서버 실행
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 로컬 파이프라인 테스트 스크립트

| 스크립트 | 설명 |
|---|---|
| `scripts/dev_run.py --audio file.wav` | SQS/S3 없이 전체 파이프라인 로컬 실행 |
| `scripts/test_models.py --audio file.wav` | VAD + 화자분리 + ASR 단독 테스트 |
| `scripts/test_pipeline.py` | Mock 데이터로 Bedrock SOAP Note 생성 테스트 |
| `scripts/ingest_rag_docs.py` | `docs/rag/` txt 파일을 pgvector에 ingestion |

## API 엔드포인트

| Method | Path | 설명 |
|---|---|---|
| `GET` | `/health/live` | 프로세스 생존 확인 |
| `GET` | `/health/ready` | DB + S3 연결 확인 |
| `POST` | `/internal/ai/analysis-jobs` | 분석 Job 수신 (BE → AI, 내부 전용 / dev 환경) |
| `GET` | `/internal/ai/analysis-jobs/{job_id}` | Job 상태 조회 (미구현, 항상 404) |
| `POST` | `/ai/rag/ingest` | RAG 문서 ingest 요청 (SQS 발행) |
| `POST` | `/ai/rag/query` | RAG 검색 테스트 |

> 운영 환경에서는 BE → SQS → CPU Worker 경로로 Job이 진입한다. `/internal/ai/analysis-jobs` 엔드포인트는 BE가 HTTP로 직접 호출하던 구 방식의 잔재로, 현재는 dev/test tooling 용도로만 유지된다.


## 배포 구조

CPU Worker와 GPU Worker를 EKS에서 분리 배포합니다.

| Worker | 담당 | 인스턴스 |
|---|---|---|
| CPU Worker | VAD, KURE 임베딩, RAG ingest | c5.xlarge |
| ML GPU Worker | pyannote 화자 분리, Whisper STT | g4dn.xlarge (T4) |
| LLM GPU Worker | EXAONE (또는 Bedrock 클라이언트) | g5.xlarge (A10G) |

## 운영 원칙

- 원본 음성, 전사 결과, 리포트는 민감 데이터로 취급한다.
- 로그에는 원문 음성, 전체 전사문, 개인정보를 남기지 않는다.
- 모든 AI 출력은 치료사 검토 대상으로 표시한다.
- RAG 답변은 검색된 근거 문서 범위 안에서만 생성한다.

## 관련 문서

| 문서 | 내용 |
|---|---|
| `docs/CODEFLOW_DETAILED.md` | 현재 코드 기준 실행 흐름, 버그 목록, 진입점 정리 |
| `docs/DATABASE_SETUP.md` | PostgreSQL + pgvector 설치 및 테이블 생성 |
| `docs/MODEL_LOADING_GUIDE.md` | HF 모델 자동 다운로드 방식, VRAM 요구사항 |
| `docs/RAG_IMPLEMENTATION.md` | RAG indexing / LangGraph query 파이프라인 |
| `docs/EKS_WORKER_ARCHITECTURE.md` | CPU/GPU Worker 분리 배포, KEDA 오토스케일링 |
| `docs/AI_PIPELINE_OPTIMIZATION.md` | 모델별 병목 분석, 최적화 방법 |
| `CONTRIBUTING.md` | 브랜치 전략, 커밋 컨벤션, PR 규칙 |
