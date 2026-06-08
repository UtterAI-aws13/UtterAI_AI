## UtterAI AI 모델 구현 상세 설계서

### 1. 문서 목적

이 문서는 `Utter_AI` 레포지토리에서 AI 모델과 RAG를 실제로 구현하기 위한 상세 설계 문서입니다.

목표는 다음과 같습니다.

1. Hugging Face 모델을 가져와서 추론 파이프라인에 연결한다.
2. 음성 파일 하나가 들어왔을 때 분석 결과가 끝까지 생성되도록 한다.
3. 모델 결과를 서비스에서 사용할 수 있는 JSON 구조로 정리한다.
4. RAG 문서 검색과 LLM 리포트 생성을 분리해서 구현한다.
5. MVP 단계에서는 파인튜닝 없이 모델 연결, 파이프라인 정렬, 데이터 저장 구조를 먼저 완성한다.

---

### 2. 전체 AI 처리 목표

UtterAI의 AI 처리는 단순히 음성을 텍스트로 바꾸는 기능이 아닙니다.

핵심 목표는 다음입니다.

```text
세션 음성
  -> 누가 언제 말했는지 파악
  -> 무슨 말을 했는지 전사
  -> 아동 발화 중심으로 언어 지표 계산
  -> 관련 치료/발달 문서를 검색
  -> 치료사가 검토할 수 있는 리포트 초안 생성
```

즉, AI 모듈은 다음 4가지 결과를 만들어야 합니다.

| 결과 | 설명 |
| --- | --- |
| Transcript | 화자별 발화 전사 결과 |
| Metrics | MLU, NDW, NTW, TTR, 반응 지연 시간 |
| Evidence | RAG로 검색된 문서 근거 |
| Draft Report | SOAP Note 또는 분석 리포트 초안 |

---

### 3. 구현 범위

#### 3.1 이번 AI 레포에서 구현할 것

- Hugging Face 모델 로딩
- 음성 파일 전처리
- VAD 추론
- 화자 분리 추론
- STT 추론
- 발화 단위 정렬
- 언어 지표 계산
- RAG 문서 ingest
- RAG 검색
- LLM 기반 리포트 초안 생성
- FastAPI 테스트 API
- Worker 기반 비동기 처리
- S3/RDS 저장 연동 인터페이스

#### 3.2 이번 AI 레포에서 구현하지 않을 것

- 프론트엔드 화면
- 사용자 로그인
- 결제
- 치료사 권한 관리
- 전체 백엔드 도메인 API
- Terraform 인프라 코드
- 모델 학습/파인튜닝
- 의료적 진단 자동 확정

---

### 4. 확정 모델과 역할

| 번호 | 단계 | 모델/도구 | 역할 | 입력 | 출력 |
| --- | --- | --- | --- | --- | --- |
| 1 | VAD | `onnx-community/silero-vad` | 말한 구간과 침묵 구간 분리 | 원본 음성 | `speech_start`, `speech_end` |
| 2 | 화자 분리 | `pyannote/speaker-diarization-3.1` | 화자별 시간 구간 분리 | 원본 음성 또는 VAD 구간 | `speaker`, `start`, `end` |
| 3 | STT/ASR | `openai/whisper-large-v3-turbo` | 음성 전사 | 음성 파일 | 텍스트, timestamp |
| 4 | 형태소 분석 | Kiwi / `kiwipiepy` | 한국어 형태소 분석 | 전사 텍스트 | 형태소, 품사, 키워드 |
| 5 | 지표 계산 | Python 로직 | MLU, NDW, NTW, TTR 계산 | 발화 목록 | 숫자 지표 |
| 6 | 임베딩 | `nlpai-lab/KURE-v1` | 문서/질의 벡터화 | 문서 chunk, 질문 | embedding vector |
| 7 | LLM | `LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct` | 리포트 초안 생성 | 지표 + 검색 근거 | SOAP Note JSON |

---

### 5. 권장 디렉터리 구조

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
│   │   ├── audio.py
│   │   ├── segment.py
│   │   ├── transcript.py
│   │   ├── metrics.py
│   │   ├── rag.py
│   │   └── report.py
│   ├── models/
│   │   ├── base.py
│   │   ├── vad_silero.py
│   │   ├── diarization_pyannote.py
│   │   ├── asr_whisper.py
│   │   ├── embedding_kure.py
│   │   └── llm_exaone.py
│   ├── pipelines/
│   │   ├── analysis_pipeline.py
│   │   ├── audio_preprocess.py
│   │   ├── alignment.py
│   │   ├── metrics_pipeline.py
│   │   └── report_pipeline.py
│   ├── metrics/
│   │   ├── mlu.py
│   │   ├── lexical_diversity.py
│   │   └── response_latency.py
│   ├── rag/
│   │   ├── ingest.py
│   │   ├── parser.py
│   │   ├── chunker.py
│   │   ├── semantic_layer.py
│   │   ├── ontology.yaml
│   │   ├── retriever.py
│   │   ├── vector_store.py
│   │   └── prompt_templates.py
│   ├── storage/
│   │   ├── s3_client.py
│   │   ├── db.py
│   │   └── repositories.py
│   ├── workers/
│   │   ├── analysis_worker.py
│   │   └── rag_ingest_worker.py
│   └── utils/
│       ├── logging.py
│       ├── audio.py
│       └── ids.py
├── scripts/
│   ├── run_local_api.sh
│   ├── run_local_worker.sh
│   ├── ingest_rag_docs.sh
│   └── download_models.py
├── tests/
│   ├── unit/
│   └── integration/
├── samples/
│   └── README.md
├── Dockerfile
├── requirements.txt
├── pyproject.toml
└── .env.example
```

---

### 6. AI 파이프라인 전체 흐름

#### 6.1 전체 순서

```text
1. Backend가 분석 Job 생성
2. 원본 음성은 S3에 저장
3. Backend가 SQS에 분석 요청 메시지 발행
4. AI Worker가 SQS 메시지 수신
5. AI Worker가 S3에서 음성 다운로드
6. 음성 포맷 검사 및 전처리
7. VAD로 발화 구간 추출
8. pyannote로 화자 분리
9. Whisper로 STT 전사
10. 화자 구간과 STT timestamp 정렬
11. 발화 단위 utterance 생성
12. Kiwi로 형태소 분석
13. MLU, NDW, NTW, TTR, 반응 지연 시간 계산
14. RAG 검색 질의 생성
15. Vector DB에서 관련 근거 검색
16. EXAONE으로 리포트 초안 생성
17. transcript/report JSON은 S3 저장
18. 메타데이터/지표/status는 RDS 저장
19. Backend가 결과 조회
```

#### 6.2 파이프라인 다이어그램

```mermaid
flowchart TD
    A[Analysis Job Created] --> B[Download Audio from S3]
    B --> C[Audio Validation]
    C --> D[Preprocess Audio]
    D --> E[Silero VAD]
    E --> F[Speech Segments]
    F --> G[Pyannote Diarization]
    G --> H[Speaker Segments]
    F --> I[Whisper ASR]
    I --> J[Transcript Segments]
    H --> K[Alignment]
    J --> K
    K --> L[Utterance List]
    L --> M[Kiwi Morph Analysis]
    M --> N[Language Metrics]
    N --> O[RAG Query Builder]
    O --> P[Semantic Layer + Ontology Expansion]
    P --> Q[Vector Search]
    Q --> R[Evidence Selection]
    R --> S[EXAONE Report Draft]
    S --> T[Save Result to S3 and RDS]
```

---

### 7. Job 상태 설계

AI 분석은 시간이 오래 걸리므로 동기 API가 아니라 비동기 Job으로 관리합니다.

| 상태 | 의미 |
| --- | --- |
| `PENDING` | Job이 생성되었지만 아직 Worker가 처리하지 않음 |
| `DOWNLOADING` | S3에서 음성 파일 다운로드 중 |
| `PREPROCESSING` | 음성 포맷 검사/변환 중 |
| `RUNNING_VAD` | VAD 처리 중 |
| `RUNNING_DIARIZATION` | 화자 분리 처리 중 |
| `RUNNING_ASR` | STT 처리 중 |
| `ALIGNING` | 화자 구간과 전사 결과 정렬 중 |
| `CALCULATING_METRICS` | 언어 지표 계산 중 |
| `RUNNING_RAG` | 관련 문서 검색 중 |
| `GENERATING_REPORT` | 리포트 초안 생성 중 |
| `SAVING_RESULT` | 결과 저장 중 |
| `COMPLETED` | 전체 분석 완료 |
| `FAILED` | 분석 실패 |
| `RETRYING` | 재시도 중 |

---

### 8. 입력 메시지 스키마

SQS 메시지 또는 내부 Job 메시지는 다음 구조를 권장합니다.

```json
{
  "job_id": "job_20260523_0001",
  "session_id": "session_001",
  "user_id": "user_001",
  "audio": {
    "bucket": "utterai-audio-dev",
    "key": "raw/session_001/original.wav",
    "content_type": "audio/wav"
  },
  "options": {
    "language": "ko",
    "enable_diarization": true,
    "enable_rag": true,
    "target_speaker_policy": "AUTO_DETECT_CHILD"
  },
  "requested_at": "2026-05-23T14:00:00+09:00"
}
```

---

### 9. 출력 결과 스키마

#### 9.1 발화 단위 결과

```json
{
  "utterance_id": "utt_0001",
  "speaker_id": "SPEAKER_01",
  "speaker_role": "CHILD",
  "start_time": 12.35,
  "end_time": 15.82,
  "duration_sec": 3.47,
  "text": "엄마 이거 봐",
  "asr_confidence": 0.91,
  "morphemes": ["엄마", "이거", "보", "아"],
  "tokens": ["엄마", "이거", "봐"]
}
```

#### 9.2 언어 지표 결과

```json
{
  "session_id": "session_001",
  "target_speaker": "CHILD",
  "metrics": {
    "total_utterances": 42,
    "ntw": 142,
    "ndw": 76,
    "ttr": 0.535,
    "mlu_morpheme": 3.8,
    "average_response_latency_sec": 1.42
  },
  "warnings": [
    "speaker_role_auto_detected",
    "short_audio_duration"
  ]
}
```

#### 9.3 RAG 근거 결과

```json
{
  "query": "아동의 평균 발화 길이와 어휘 다양성을 어떻게 해석해야 하는가?",
  "expanded_query": [
    "MLU",
    "평균 발화 길이",
    "어휘 다양도",
    "NDW",
    "TTR",
    "언어발달 평가"
  ],
  "evidence": [
    {
      "document_id": "doc_001",
      "chunk_id": "chunk_0014",
      "title": "언어발달 평가 가이드",
      "source_type": "clinical_guide",
      "score": 0.82,
      "text": "검색된 chunk 본문 일부",
      "metadata": {
        "age_group": "preschool",
        "language_area": "expressive_language"
      }
    }
  ]
}
```

#### 9.4 리포트 결과

```json
{
  "report_id": "report_001",
  "job_id": "job_20260523_0001",
  "session_id": "session_001",
  "report_type": "SOAP_NOTE_DRAFT",
  "model_versions": {
    "vad": "onnx-community/silero-vad",
    "diarization": "pyannote/speaker-diarization-3.1",
    "asr": "openai/whisper-large-v3-turbo",
    "embedding": "nlpai-lab/KURE-v1",
    "llm": "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct"
  },
  "soap_note": {
    "subjective": "보호자 또는 치료사 관찰 내용 요약",
    "objective": "전사 결과와 정량 지표 기반 관찰",
    "assessment": "검색 근거와 지표를 바탕으로 한 해석 초안",
    "plan": "다음 회기에서 고려할 활동 또는 관찰 포인트"
  },
  "evidence_chunk_ids": ["chunk_0014", "chunk_0020"],
  "requires_human_review": true
}
```

---

### 10. 모델 래퍼 설계

모델을 직접 파이프라인에 섞으면 코드가 금방 복잡해집니다.  
각 모델은 공통 인터페이스를 가진 Wrapper 클래스로 감싸는 것이 좋습니다.

#### 10.1 기본 모델 인터페이스

```python
# app/models/base.py

from abc import ABC, abstractmethod
from typing import Any


class BaseModelWrapper(ABC):
    model_name: str

    @abstractmethod
    def load(self) -> None:
        pass

    @abstractmethod
    def predict(self, input_data: Any) -> Any:
        pass

    def unload(self) -> None:
        pass
```

#### 10.2 VAD Wrapper 예시

```python
# app/models/vad_silero.py

from app.models.base import BaseModelWrapper


class SileroVADWrapper(BaseModelWrapper):
    def __init__(self, model_name: str, threshold: float = 0.5):
        self.model_name = model_name
        self.threshold = threshold
        self.model = None

    def load(self) -> None:
        # 실제 구현에서는 Hugging Face 또는 ONNX Runtime 기반으로 로드
        # self.model = ...
        pass

    def predict(self, audio_path: str) -> list[dict]:
        # 반환 예시:
        # [
        #   {"start": 1.20, "end": 3.84, "confidence": 0.94},
        #   {"start": 5.10, "end": 8.02, "confidence": 0.91}
        # ]
        pass
```

#### 10.3 ASR Wrapper 예시

```python
# app/models/asr_whisper.py

from app.models.base import BaseModelWrapper


class WhisperASRWrapper(BaseModelWrapper):
    def __init__(self, model_name: str, device: str = "cuda"):
        self.model_name = model_name
        self.device = device
        self.pipeline = None

    def load(self) -> None:
        # transformers pipeline 또는 faster-whisper 방식 중 하나를 선택
        pass

    def predict(self, audio_path: str) -> dict:
        # 반환 예시:
        # {
        #   "text": "...",
        #   "segments": [
        #     {"start": 1.0, "end": 2.5, "text": "안녕하세요"}
        #   ]
        # }
        pass
```

---

### 11. 음성 전처리 설계

#### 11.1 전처리 목적

음성 모델들은 입력 포맷에 민감합니다.  
따라서 원본 파일이 mp3, m4a, wav 등 어떤 형식이든 내부 처리 전에는 통일된 형식으로 변환합니다.

권장 내부 표준:

| 항목 | 권장값 |
| --- | --- |
| format | WAV |
| sample rate | 16kHz |
| channel | mono |
| bit depth | 16-bit PCM |

#### 11.2 처리 흐름

```text
원본 파일 다운로드
  -> 파일 확장자/크기 검사
  -> ffmpeg로 wav 변환
  -> 16kHz mono 변환
  -> duration 측정
  -> 너무 짧거나 긴 파일 검사
  -> 전처리 파일 S3 저장
```

#### 11.3 전처리 결과 예시

```json
{
  "original_s3_key": "raw/session_001/original.m4a",
  "processed_s3_key": "processed/session_001/audio_16k_mono.wav",
  "duration_sec": 642.2,
  "sample_rate": 16000,
  "channels": 1,
  "format": "wav"
}
```

---

### 12. VAD 구현 상세

#### 12.1 VAD의 역할

VAD는 Voice Activity Detection의 약자입니다.  
음성 파일에서 실제로 사람이 말한 구간과 침묵 구간을 분리합니다.

이 단계가 필요한 이유는 다음과 같습니다.

1. STT 처리량을 줄일 수 있습니다.
2. 긴 침묵 구간을 제외할 수 있습니다.
3. 반응 지연 시간 계산의 기초가 됩니다.
4. 화자 분리와 발화 단위 정렬의 기준 시간이 됩니다.

#### 12.2 입력

```text
processed/session_001/audio_16k_mono.wav
```

#### 12.3 출력

```json
[
  {
    "segment_id": "speech_0001",
    "start_time": 1.24,
    "end_time": 4.85,
    "duration_sec": 3.61,
    "confidence": 0.94
  },
  {
    "segment_id": "speech_0002",
    "start_time": 6.02,
    "end_time": 9.31,
    "duration_sec": 3.29,
    "confidence": 0.92
  }
]
```

#### 12.4 주요 파라미터

| 파라미터 | 설명 | MVP 기본값 |
| --- | --- | --- |
| `threshold` | 음성으로 판단할 확률 기준 | `0.5` |
| `min_speech_duration_ms` | 너무 짧은 발화를 제거하는 기준 | `250` |
| `min_silence_duration_ms` | 침묵으로 분리할 최소 길이 | `500` |
| `speech_pad_ms` | 발화 앞뒤에 붙일 여유 시간 | `100` |

---

### 13. 화자 분리 구현 상세

#### 13.1 화자 분리의 역할

화자 분리는 한 음성 파일 안에서 누가 언제 말했는지 구분하는 작업입니다.

UtterAI에서는 최소한 다음 화자를 구분해야 합니다.

| speaker_role | 설명 |
| --- | --- |
| `CHILD` | 아동 |
| `THERAPIST` | 치료사 |
| `CAREGIVER` | 보호자 |
| `UNKNOWN` | 자동 판단이 어려운 화자 |

초기 MVP에서는 pyannote가 생성한 `SPEAKER_00`, `SPEAKER_01`을 그대로 저장하고, 이후 규칙 또는 치료사 검토로 역할을 매핑합니다.

#### 13.2 출력 예시

```json
[
  {
    "speaker_segment_id": "spkseg_0001",
    "speaker_id": "SPEAKER_00",
    "speaker_role": "UNKNOWN",
    "start_time": 0.80,
    "end_time": 4.90
  },
  {
    "speaker_segment_id": "spkseg_0002",
    "speaker_id": "SPEAKER_01",
    "speaker_role": "UNKNOWN",
    "start_time": 5.20,
    "end_time": 8.70
  }
]
```

#### 13.3 speaker_role 매핑 전략

초기에는 자동으로 완벽히 `CHILD`, `THERAPIST`를 판단하기 어렵습니다.  
따라서 다음 순서로 접근합니다.

1. pyannote 결과를 `SPEAKER_00`, `SPEAKER_01` 형태로 저장한다.
2. 각 speaker의 발화량, 평균 pitch, 발화 길이 등을 계산한다.
3. 추정 규칙으로 `likely_child`, `likely_therapist`를 표시한다.
4. 치료사 화면에서 speaker role을 수정할 수 있게 한다.
5. 수정 결과를 RDS에 저장해서 리포트 생성 시 사용한다.

MVP에서는 자동 판단보다 **수정 가능한 구조**가 중요합니다.

---

### 14. STT/ASR 구현 상세

#### 14.1 ASR의 역할

ASR은 Automatic Speech Recognition의 약자입니다.  
음성을 텍스트로 변환합니다.

UtterAI에서는 단순 전사뿐 아니라 timestamp가 중요합니다.  
timestamp가 있어야 화자 분리 결과와 합쳐서 `누가 어떤 말을 했는지`를 만들 수 있습니다.

#### 14.2 출력 예시

```json
{
  "text": "안녕하세요 오늘은 그림 카드를 보고 이야기해볼게요",
  "segments": [
    {
      "asr_segment_id": "asr_0001",
      "start_time": 0.95,
      "end_time": 3.42,
      "text": "안녕하세요 오늘은 그림 카드를 보고",
      "confidence": 0.89
    },
    {
      "asr_segment_id": "asr_0002",
      "start_time": 3.42,
      "end_time": 5.20,
      "text": "이야기해볼게요",
      "confidence": 0.87
    }
  ]
}
```

#### 14.3 ASR 후처리

Whisper 출력은 그대로 사용하지 않고 다음 후처리를 합니다.

| 후처리 | 설명 |
| --- | --- |
| 공백 정리 | 중복 공백 제거 |
| 반복어 처리 | 너무 긴 반복 전사 검사 |
| 무의미 토큰 제거 | 음악, 잡음, 괄호 표현 등 제거 |
| 문장 분리 | 발화 단위 계산을 위해 문장 경계 정리 |
| timestamp 보정 | VAD/diarization 구간과 맞추기 위해 시간 정렬 |

---

### 15. 발화 정렬 구현

#### 15.1 왜 정렬이 필요한가

VAD, diarization, ASR은 각각 다른 결과를 냅니다.

| 결과 | 기준 |
| --- | --- |
| VAD | 말소리가 있는 구간 |
| Diarization | 화자별 시간 구간 |
| ASR | 텍스트와 timestamp |
| Utterance | 서비스에서 실제로 사용할 발화 단위 |

따라서 이 세 결과를 합쳐야 합니다.

```text
VAD Segment + Speaker Segment + ASR Segment
  -> Utterance
```

#### 15.2 정렬 기준

가장 단순한 MVP 기준은 **시간 구간 overlap**입니다.

```text
ASR segment의 start/end와
speaker segment의 start/end가 가장 많이 겹치는 speaker를 선택
```

#### 15.3 정렬 결과 예시

```json
{
  "utterance_id": "utt_0007",
  "speaker_id": "SPEAKER_01",
  "speaker_role": "CHILD",
  "start_time": 21.30,
  "end_time": 23.10,
  "text": "강아지가 뛰어가요",
  "source": {
    "vad_segment_id": "speech_0005",
    "speaker_segment_id": "spkseg_0011",
    "asr_segment_id": "asr_0009"
  }
}
```

#### 15.4 overlap 계산 예시

```python
def calculate_overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    overlap_start = max(a_start, b_start)
    overlap_end = min(a_end, b_end)
    return max(0.0, overlap_end - overlap_start)
```

---

### 16. 언어 지표 계산 상세

#### 16.1 지표 계산 대상

기본적으로 언어 지표는 전체 화자가 아니라 **아동 발화**를 기준으로 계산합니다.

```text
전체 utterance
  -> speaker_role == CHILD 필터링
  -> 아동 발화만 대상으로 지표 계산
```

speaker_role이 확정되지 않은 경우에는 다음 방식 중 하나를 선택합니다.

1. 치료사가 speaker_role을 먼저 지정하게 한다.
2. 가장 짧고 단순한 발화가 많은 speaker를 임시 CHILD로 추정한다.
3. 전체 speaker별 지표를 모두 보여주고 사용자가 선택하게 한다.

MVP에서는 3번 방식이 가장 안전합니다.

---

#### 16.2 NTW

NTW는 Number of Total Words입니다.  
분석 대상 발화에 등장한 전체 단어 수입니다.

```text
NTW = 전체 단어 수
```

예시:

```text
발화1: "강아지가 뛰어가요" -> 2단어
발화2: "나도 할래요" -> 2단어

NTW = 4
```

---

#### 16.3 NDW

NDW는 Number of Different Words입니다.  
중복을 제거한 서로 다른 단어 수입니다.

```text
NDW = 중복 제거 후 단어 수
```

예시:

```text
발화1: "강아지가 뛰어가요"
발화2: "강아지가 먹어요"

단어 목록 = ["강아지가", "뛰어가요", "강아지가", "먹어요"]
중복 제거 = ["강아지가", "뛰어가요", "먹어요"]

NDW = 3
```

---

#### 16.4 TTR

TTR은 Type Token Ratio입니다.  
전체 단어 수 대비 서로 다른 단어 수의 비율입니다.

```text
TTR = NDW / NTW
```

예시:

```text
NTW = 100
NDW = 45

TTR = 45 / 100 = 0.45
```

TTR은 발화량이 많아질수록 낮아지는 경향이 있으므로, 리포트에서는 단독 판단보다 참고 지표로 사용합니다.

---

#### 16.5 MLU

MLU는 Mean Length of Utterance입니다.  
평균 발화 길이를 의미합니다.

언어치료 영역에서는 단어 기준 MLU와 형태소 기준 MLU를 구분할 수 있습니다.  
한국어에서는 조사, 어미가 의미를 가지므로 MVP에서는 Kiwi 형태소 분석 결과를 활용한 **형태소 기준 MLU**를 우선 계산합니다.

```text
MLU = 전체 형태소 수 / 전체 발화 수
```

예시:

```text
발화1: "강아지가 뛰어가요" -> 강아지/가/뛰/어/가/요 = 6개
발화2: "나도 할래요" -> 나/도/하/ㄹ래/요 = 5개

전체 형태소 수 = 11
전체 발화 수 = 2

MLU = 11 / 2 = 5.5
```

---

#### 16.6 반응 지연 시간

반응 지연 시간은 치료사 발화가 끝난 뒤 아동 발화가 시작되기까지 걸린 시간입니다.

```text
Response Latency = child_utterance.start_time - therapist_utterance.end_time
```

예시:

```text
치료사 발화 종료: 10.20초
아동 발화 시작: 11.80초

반응 지연 시간 = 1.60초
```

MVP에서는 다음 조건을 만족할 때만 계산합니다.

1. 이전 발화자가 `THERAPIST`
2. 다음 발화자가 `CHILD`
3. 두 발화 사이 간격이 음수 또는 비정상적으로 길지 않음
4. 중간에 다른 speaker 발화가 없음

---

### 17. Kiwi 형태소 분석 설계

#### 17.1 사용 목적

Kiwi는 다음 두 영역에서 사용합니다.

| 영역 | 사용 방식 |
| --- | --- |
| 언어 지표 계산 | 형태소 기준 MLU 계산 |
| RAG 질의 확장 | 핵심 명사/용어 추출 |

#### 17.2 형태소 분석 결과 예시

```json
{
  "text": "강아지가 뛰어가요",
  "morphemes": [
    {"form": "강아지", "tag": "NNG"},
    {"form": "가", "tag": "JKS"},
    {"form": "뛰", "tag": "VV"},
    {"form": "어", "tag": "EC"},
    {"form": "가", "tag": "VX"},
    {"form": "요", "tag": "EF"}
  ]
}
```

#### 17.3 RAG 키워드 추출 기준

RAG 질의 확장에는 모든 형태소를 쓰지 않습니다.  
주로 다음 품사를 활용합니다.

| 품사 | 설명 |
| --- | --- |
| `NNG` | 일반 명사 |
| `NNP` | 고유 명사 |
| `VV` | 동사 |
| `VA` | 형용사 |
| `SL` | 외국어/약어 |

예시:

```text
원문 질문:
"아동의 MLU가 낮고 TTR도 낮게 나왔는데 어떻게 해석해야 해?"

추출 키워드:
["아동", "MLU", "TTR", "낮", "해석"]
```

---

### 18. RAG 구현 상세

#### 18.1 RAG의 역할

RAG는 Retrieval-Augmented Generation입니다.  
LLM이 자기 지식만으로 답하는 것이 아니라, 미리 저장된 문서를 검색한 뒤 그 근거를 바탕으로 답변하게 만드는 구조입니다.

UtterAI에서 RAG는 다음에 사용합니다.

1. 언어발달 평가 기준 검색
2. MLU, NDW, TTR 해석 기준 검색
3. 치료 활동 가이드 검색
4. SOAP Note 문장 작성 참고
5. 치료사가 확인할 근거 문서 제공

---

### 19. RAG 문서 종류

RAG에 넣을 문서는 다음 유형으로 나눕니다.

| 문서 유형 | 예시 |
| --- | --- |
| 평가 기준 문서 | 언어발달 평가 가이드, 검사 해석 기준 |
| 치료 활동 문서 | 조음/언어/상호작용 활동 가이드 |
| 리포트 템플릿 | SOAP Note 예시, 세션 기록 양식 |
| 내부 운영 문서 | 서비스에서 사용하는 해석 규칙 |
| 논문/자료 요약 | 언어치료 관련 연구 요약 |

---

### 20. RAG ingest 흐름

```text
원본 문서 업로드
  -> 문서 파싱
  -> 텍스트 정제
  -> 의미 단위 chunking
  -> metadata 부여
  -> embedding 생성
  -> pgvector 저장
```

#### 20.1 chunk metadata 예시

```json
{
  "document_id": "doc_001",
  "chunk_id": "chunk_0014",
  "title": "언어발달 평가 가이드",
  "source_type": "clinical_guide",
  "age_group": "preschool",
  "language_area": "expressive_language",
  "metric": ["MLU", "NDW", "TTR"],
  "page": 12,
  "section": "표현언어 평가",
  "created_at": "2026-05-23T14:00:00+09:00"
}
```

---

### 21. Chunking 전략

#### 21.1 단순 길이 기준 chunking의 문제

단순히 500자마다 자르면 문맥이 끊길 수 있습니다.

예시:

```text
MLU의 정의는 앞 chunk에 있고
해석 기준은 다음 chunk에 있는 경우
검색 결과가 불완전해질 수 있음
```

#### 21.2 권장 방식

MVP에서는 다음 방식을 권장합니다.

| 전략 | 설명 |
| --- | --- |
| 의미 단위 chunking | 제목, 문단, 표 단위로 자르기 |
| parent-child chunking | 큰 문단 parent와 작은 검색 chunk를 함께 저장 |
| overlap 적용 | 앞뒤 문맥 일부를 겹치게 저장 |
| metadata 강화 | age_group, metric, language_area 등 필터링 정보 저장 |

#### 21.3 chunk 크기 권장값

| 항목 | 권장값 |
| --- | --- |
| child chunk | 300~700 tokens |
| parent chunk | 1,000~2,000 tokens |
| overlap | 50~100 tokens |

---

### 22. Semantic Layer와 Ontology

#### 22.1 Semantic Layer의 역할

Semantic Layer는 사용자의 질문을 그대로 Vector DB에 던지기 전에, 서비스 도메인에 맞는 검색 의도로 바꿔주는 계층입니다.

예시:

```text
사용자 질문:
"말이 좀 짧게 나왔는데 괜찮은 건가?"

Semantic Layer 변환:
- 관련 개념: MLU, 평균 발화 길이, 표현언어, 발화 복잡도
- 검색 필터: language_area = expressive_language
- 우선 문서: 평가 기준, SOAP Note 템플릿
```

#### 22.2 Ontology의 역할

Ontology는 도메인 개념 사이의 관계를 정의한 사전입니다.

예시:

```yaml
concepts:
  MLU:
    ko: "평균 발화 길이"
    related_terms:
      - "발화 길이"
      - "형태소 수"
      - "문장 길이"
      - "표현언어"
    metrics:
      - "mlu_morpheme"
    language_area:
      - "expressive_language"

  TTR:
    ko: "어휘 다양도"
    related_terms:
      - "Type Token Ratio"
      - "어휘 다양성"
      - "NDW"
      - "NTW"
    metrics:
      - "ttr"
      - "ndw"
      - "ntw"
    language_area:
      - "vocabulary"
```

#### 22.3 MVP 구현 방식

처음부터 복잡한 지식 그래프를 만들 필요는 없습니다.  
MVP에서는 `ontology.yaml` 파일 하나로 시작합니다.

```text
질문 입력
  -> Kiwi로 키워드 추출
  -> ontology.yaml에서 관련 개념 조회
  -> 동의어/관련어 확장
  -> metadata filter 생성
  -> Vector DB 검색
```

---

### 23. Retriever 설계

#### 23.1 검색 입력

```json
{
  "question": "아동의 MLU가 낮게 나왔는데 어떻게 해석해야 하나요?",
  "session_metrics": {
    "mlu_morpheme": 2.8,
    "ndw": 42,
    "ttr": 0.41
  },
  "filters": {
    "age_group": "preschool",
    "language_area": "expressive_language"
  }
}
```

#### 23.2 검색 단계

```text
1. 질문 정규화
2. Kiwi 키워드 추출
3. Ontology 기반 질의 확장
4. KURE-v1으로 query embedding 생성
5. pgvector에서 top_k 검색
6. metadata filter 적용
7. 중복 chunk 제거
8. evidence 후보 정렬
9. LLM에 넣을 근거만 선택
```

#### 23.3 검색 결과

```json
{
  "question": "아동의 MLU가 낮게 나왔는데 어떻게 해석해야 하나요?",
  "retrieved_chunks": [
    {
      "chunk_id": "chunk_0014",
      "document_id": "doc_001",
      "title": "언어발달 평가 가이드",
      "score": 0.84,
      "text": "MLU는 아동의 평균 발화 길이를 나타내며...",
      "metadata": {
        "metric": ["MLU"],
        "language_area": "expressive_language"
      }
    }
  ]
}
```

---

### 24. Vector DB 설계

#### 24.1 MVP 선택

MVP에서는 PostgreSQL에 `pgvector` 확장을 붙이는 구조가 가장 단순합니다.

이유는 다음과 같습니다.

1. RDS PostgreSQL과 같은 DB 계열로 관리하기 쉽습니다.
2. 별도 Vector DB 운영 부담이 줄어듭니다.
3. 문서 chunk 메타데이터와 벡터를 함께 저장하기 좋습니다.
4. MVP 규모에서는 충분히 테스트 가능합니다.

#### 24.2 테이블 예시

```sql
CREATE TABLE rag_documents (
    document_id VARCHAR(64) PRIMARY KEY,
    title TEXT NOT NULL,
    source_type VARCHAR(64),
    s3_key TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE rag_chunks (
    chunk_id VARCHAR(64) PRIMARY KEY,
    document_id VARCHAR(64) REFERENCES rag_documents(document_id),
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB,
    embedding vector(1024),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

`embedding vector(1024)`의 차원 수는 실제 KURE-v1 임베딩 차원에 맞춰 조정해야 합니다.

---

### 25. LLM 리포트 생성 설계

#### 25.1 LLM 입력 구성

LLM에는 원본 음성 전체나 전체 전사문을 무작정 넣지 않습니다.  
다음 정보만 정리해서 넣습니다.

| 입력 | 설명 |
| --- | --- |
| session summary | 세션 전체 요약 |
| speaker metrics | 화자별/아동 기준 언어 지표 |
| selected utterances | 대표 발화 일부 |
| retrieved evidence | RAG 검색 근거 chunk |
| output schema | JSON 출력 형식 |
| safety instruction | 진단 확정 금지, 치료사 검토 필요 |

#### 25.2 프롬프트 원칙

```text
- 검색된 근거 문서에 없는 내용은 단정하지 않는다.
- 아동을 진단하지 않는다.
- 치료사가 검토할 초안이라고 명시한다.
- 지표 수치를 그대로 인용하되 과도한 해석을 피한다.
- 출력은 반드시 JSON schema를 따른다.
```

#### 25.3 출력 JSON Schema 예시

```json
{
  "soap_note": {
    "subjective": "string",
    "objective": "string",
    "assessment": "string",
    "plan": "string"
  },
  "clinical_flags": [
    {
      "type": "string",
      "description": "string",
      "evidence_chunk_ids": ["string"]
    }
  ],
  "recommended_review_points": ["string"],
  "disclaimer": "치료사 검토가 필요한 AI 생성 초안입니다."
}
```

---

### 26. 데이터베이스 논리 설계

#### 26.1 주요 테이블

| 테이블 | 역할 |
| --- | --- |
| `analysis_jobs` | AI 분석 Job 상태 관리 |
| `audio_files` | S3 오디오 파일 메타데이터 |
| `speech_segments` | VAD 결과 |
| `speaker_segments` | 화자 분리 결과 |
| `utterances` | 최종 발화 단위 |
| `language_metrics` | MLU, NDW, NTW, TTR 등 지표 |
| `rag_documents` | RAG 문서 메타데이터 |
| `rag_chunks` | RAG chunk 및 embedding |
| `report_drafts` | AI 리포트 초안 |
| `report_review_history` | 치료사 수정/승인 이력 |

#### 26.2 `analysis_jobs` 예시

```sql
CREATE TABLE analysis_jobs (
    job_id VARCHAR(64) PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    current_step VARCHAR(64),
    error_code VARCHAR(64),
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP
);
```

#### 26.3 `utterances` 예시

```sql
CREATE TABLE utterances (
    utterance_id VARCHAR(64) PRIMARY KEY,
    job_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    speaker_id VARCHAR(64),
    speaker_role VARCHAR(32),
    start_time DOUBLE PRECISION,
    end_time DOUBLE PRECISION,
    text TEXT,
    asr_confidence DOUBLE PRECISION,
    morphemes JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### 26.4 `language_metrics` 예시

```sql
CREATE TABLE language_metrics (
    metric_id VARCHAR(64) PRIMARY KEY,
    job_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    speaker_id VARCHAR(64),
    speaker_role VARCHAR(32),
    total_utterances INT,
    ntw INT,
    ndw INT,
    ttr DOUBLE PRECISION,
    mlu_morpheme DOUBLE PRECISION,
    average_response_latency_sec DOUBLE PRECISION,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

### 27. S3 Key 설계

S3에는 큰 파일과 긴 JSON 결과를 저장합니다.

```text
s3://utterai-audio-dev/
├── raw/
│   └── {session_id}/original.{ext}
├── processed/
│   └── {session_id}/audio_16k_mono.wav
├── segments/
│   └── {session_id}/{segment_id}.wav
└── transcripts/
    └── {session_id}/{job_id}.json

s3://utterai-report-dev/
└── reports/
    └── {session_id}/{report_id}.json

s3://utterai-rag-dev/
├── raw-documents/
│   └── {document_id}/{filename}
└── parsed/
    └── {document_id}/parsed.json
```

---

### 28. FastAPI API 설계

#### 28.1 Health API

```http
GET /health/live
GET /health/ready
```

`/health/live`는 프로세스가 살아있는지만 확인합니다.  
`/health/ready`는 DB, S3, 모델 로딩 상태까지 확인합니다.

#### 28.2 분석 Job 생성

```http
POST /ai/jobs
```

요청:

```json
{
  "session_id": "session_001",
  "audio_s3_key": "raw/session_001/original.wav",
  "options": {
    "enable_diarization": true,
    "enable_rag": true
  }
}
```

응답:

```json
{
  "job_id": "job_20260523_0001",
  "status": "PENDING"
}
```

#### 28.3 분석 Job 조회

```http
GET /ai/jobs/{job_id}
```

응답:

```json
{
  "job_id": "job_20260523_0001",
  "status": "RUNNING_ASR",
  "progress": 0.52,
  "current_step": "Whisper STT running"
}
```

#### 28.4 RAG 검색 테스트

```http
POST /ai/rag/query
```

요청:

```json
{
  "question": "MLU가 낮게 나왔을 때 어떻게 해석하나요?",
  "filters": {
    "age_group": "preschool"
  }
}
```

---

### 29. Worker 설계

#### 29.1 Worker가 필요한 이유

음성 분석과 LLM 생성은 시간이 오래 걸립니다.  
API 요청 하나에서 바로 처리하면 timeout이 발생할 수 있습니다.

따라서 구조는 다음처럼 분리합니다.

```text
Backend API
  -> Job 생성
  -> SQS 메시지 발행
  -> 즉시 job_id 반환

AI Worker
  -> SQS 메시지 수신
  -> 긴 분석 작업 수행
  -> 결과 저장
```

#### 29.2 Worker 처리 의사코드

```python
def handle_analysis_job(message: dict) -> None:
    job_id = message["job_id"]

    update_job_status(job_id, "DOWNLOADING")
    audio_path = download_audio_from_s3(message["audio"])

    update_job_status(job_id, "PREPROCESSING")
    processed_audio = preprocess_audio(audio_path)

    update_job_status(job_id, "RUNNING_VAD")
    speech_segments = vad_model.predict(processed_audio)

    update_job_status(job_id, "RUNNING_DIARIZATION")
    speaker_segments = diarization_model.predict(processed_audio)

    update_job_status(job_id, "RUNNING_ASR")
    transcript_segments = asr_model.predict(processed_audio)

    update_job_status(job_id, "ALIGNING")
    utterances = align_segments(
        speech_segments=speech_segments,
        speaker_segments=speaker_segments,
        transcript_segments=transcript_segments,
    )

    update_job_status(job_id, "CALCULATING_METRICS")
    metrics = calculate_language_metrics(utterances)

    update_job_status(job_id, "RUNNING_RAG")
    evidence = retrieve_evidence(metrics, utterances)

    update_job_status(job_id, "GENERATING_REPORT")
    report = generate_report(metrics, utterances, evidence)

    update_job_status(job_id, "SAVING_RESULT")
    save_results(job_id, utterances, metrics, evidence, report)

    update_job_status(job_id, "COMPLETED")
```

---

### 30. CPU Worker와 GPU Worker 분리

#### 30.1 CPU에 적합한 작업

| 작업 | 이유 |
| --- | --- |
| 음성 파일 검증 | 가벼운 I/O 작업 |
| ffmpeg 전처리 | CPU 처리 가능 |
| Silero VAD | ONNX 기반으로 CPU 처리 가능 |
| Kiwi 형태소 분석 | CPU 처리 가능 |
| 언어 지표 계산 | 단순 계산 |
| RAG 검색 API | 초기 규모에서는 CPU 가능 |
| DB/S3 저장 | I/O 중심 |

#### 30.2 GPU에 적합한 작업

| 작업 | 이유 |
| --- | --- |
| pyannote 화자 분리 | 음성 딥러닝 추론 비용이 큼 |
| Whisper STT | 긴 음성 전사 시 GPU 필요 |
| EXAONE 리포트 생성 | LLM 추론 비용이 큼 |
| KURE 임베딩 대량 생성 | 문서가 많으면 GPU 배치 처리 유리 |

#### 30.3 배포 관점

MVP에서는 다음처럼 시작할 수 있습니다.

```text
FastAPI API Server: ECS Fargate 또는 EKS CPU Node
CPU Worker: ECS Fargate 또는 EKS CPU Node
GPU Worker: GPU EC2 또는 EKS GPU Node Group
```

이후 발표에서는 다음처럼 정리할 수 있습니다.

```text
현재는 MVP 구상 단계이므로 ECS/Fargate 기반 CPU Worker 중심으로 시작하고,
Whisper, pyannote, EXAONE처럼 GPU가 필요한 모델은 추후 EKS GPU Worker Node Group으로 확장할 수 있게 분리 설계한다.
```

---

### 31. 에러 처리 설계

#### 31.1 에러 유형

| 에러 코드 | 상황 | 처리 |
| --- | --- | --- |
| `AUDIO_NOT_FOUND` | S3에 파일 없음 | Job 실패 처리 |
| `INVALID_AUDIO_FORMAT` | 지원하지 않는 음성 형식 | 사용자에게 재업로드 요청 |
| `AUDIO_TOO_SHORT` | 분석하기에 너무 짧음 | 실패 또는 경고 처리 |
| `VAD_NO_SPEECH` | 말소리 감지 실패 | 리포트 생성 중단 |
| `DIARIZATION_FAILED` | 화자 분리 실패 | speaker unknown으로 fallback |
| `ASR_FAILED` | STT 실패 | 재시도 |
| `RAG_NO_EVIDENCE` | 검색 근거 없음 | 리포트에 근거 부족 표시 |
| `LLM_OUTPUT_INVALID` | LLM JSON 파싱 실패 | 재시도 또는 schema repair |
| `DB_SAVE_FAILED` | DB 저장 실패 | 재시도 |
| `S3_SAVE_FAILED` | S3 저장 실패 | 재시도 |

#### 31.2 실패 시 저장할 정보

```json
{
  "job_id": "job_001",
  "status": "FAILED",
  "failed_step": "RUNNING_ASR",
  "error_code": "ASR_FAILED",
  "error_message": "ASR model inference timeout",
  "retryable": true
}
```

---

### 32. 로깅 원칙

음성, 전사문, 개인정보는 민감 데이터입니다.  
로그에는 다음 정보를 남기지 않습니다.

- 원본 음성 내용
- 전체 전사문
- 보호자/아동 이름
- 주민번호, 전화번호, 주소 등 개인정보
- 리포트 전문

로그에 남길 수 있는 정보는 다음입니다.

```json
{
  "event": "analysis_step_completed",
  "job_id": "job_001",
  "session_id": "session_001",
  "step": "RUNNING_ASR",
  "duration_ms": 12840,
  "status": "success"
}
```

---

### 33. 모델 버전 관리

모델은 단순히 이름만 저장하면 안 됩니다.  
나중에 결과가 달라졌을 때 어떤 모델로 생성했는지 추적할 수 있어야 합니다.

저장 권장 정보:

| 항목 | 설명 |
| --- | --- |
| model_name | Hugging Face 모델명 |
| model_revision | 특정 commit hash 또는 revision |
| runtime | transformers, onnxruntime 등 |
| device | cpu, cuda |
| prompt_version | LLM 프롬프트 버전 |
| ontology_version | RAG ontology 버전 |
| rag_document_version | 검색 문서 버전 |

---

### 34. 보안과 개인정보 처리

#### 34.1 기본 원칙

- 원본 음성은 S3에 저장한다.
- RDS에는 음성 파일 자체를 넣지 않고 S3 key만 저장한다.
- S3 bucket은 private으로 둔다.
- 접근은 presigned URL 또는 IAM Role 기반으로 제한한다.
- 로그에는 민감 데이터 원문을 남기지 않는다.
- 리포트 생성 결과는 치료사 검토 전에는 확정 결과로 표시하지 않는다.

#### 34.2 S3 암호화

권장 설정:

```text
S3 Block Public Access: Enabled
S3 Server-Side Encryption: SSE-S3 또는 SSE-KMS
Bucket Policy: 최소 권한
Object Key: session_id/job_id 기반 분리
Lifecycle Policy: 보존 기간 이후 삭제 또는 Glacier 이동
```

#### 34.3 DB 접근

```text
AI Worker Security Group
  -> RDS Security Group: 5432 허용

외부 인터넷
  -> RDS 직접 접근 불가
```

---

### 35. 테스트 전략

#### 35.1 Unit Test

| 테스트 | 대상 |
| --- | --- |
| VAD output schema test | VAD 결과 형태 검증 |
| overlap calculation test | 발화 정렬 로직 검증 |
| MLU calculation test | 형태소 수 기반 MLU 계산 |
| TTR calculation test | NDW/NTW 계산 |
| ontology expansion test | RAG 질의 확장 |
| prompt output parser test | LLM JSON 파싱 |

#### 35.2 Integration Test

| 테스트 | 설명 |
| --- | --- |
| sample audio end-to-end | 샘플 음성 1개로 전체 파이프라인 실행 |
| RAG ingest and query | 문서 ingest 후 검색 결과 확인 |
| report draft generation | metrics + evidence로 리포트 JSON 생성 |
| S3 save test | 결과 파일 저장 확인 |
| DB save test | Job status와 metrics 저장 확인 |

#### 35.3 평가 지표

| 영역 | 지표 |
| --- | --- |
| STT | WER, CER |
| 화자 분리 | DER |
| RAG | Recall@k, MRR, 근거 적합성 |
| LLM 리포트 | JSON valid rate, 근거 충실도, 치료사 수정률 |
| 성능 | 평균 처리 시간, p95 처리 시간 |
| 안정성 | Job 실패율, 재시도 성공률 |

---

### 36. 구현 순서 상세

#### 36.1 1단계: 레포 기본 세팅

```bash
mkdir -p app/{api,schemas,models,pipelines,metrics,rag,storage,workers,utils}
mkdir -p docs tests/{unit,integration} scripts samples
touch app/main.py app/config.py
touch README.md docs/AI_IMPLEMENTATION_GUIDE.md
touch requirements.txt .env.example Dockerfile
```

#### 36.2 2단계: 공통 Schema 작성

먼저 모델 코드를 붙이기 전에 데이터 구조를 정합니다.

필수 schema:

```text
JobMessage
AudioMetadata
SpeechSegment
SpeakerSegment
ASRSegment
Utterance
LanguageMetrics
RagEvidence
ReportDraft
```

#### 36.3 3단계: VAD 단독 실행

목표:

```text
음성 파일 입력
  -> speech segment JSON 출력
```

완료 기준:

- 샘플 wav 파일을 넣으면 말한 구간이 출력된다.
- 결과가 `SpeechSegment` schema를 통과한다.
- 결과 JSON을 S3 저장 형식으로 만들 수 있다.

#### 36.4 4단계: Whisper 단독 실행

목표:

```text
음성 파일 입력
  -> timestamp 포함 transcript JSON 출력
```

완료 기준:

- 한국어 음성이 텍스트로 전사된다.
- segment별 start/end가 존재한다.
- 전체 text와 segment list를 모두 저장한다.

#### 36.5 5단계: pyannote 단독 실행

목표:

```text
음성 파일 입력
  -> speaker segment JSON 출력
```

완료 기준:

- `SPEAKER_00`, `SPEAKER_01` 형태의 결과가 나온다.
- start/end 시간이 존재한다.
- speaker별 총 발화 시간이 계산된다.

#### 36.6 6단계: 발화 정렬

목표:

```text
speaker segment + asr segment
  -> speaker가 붙은 utterance 생성
```

완료 기준:

- 각 utterance에 speaker_id가 붙는다.
- overlap 기준으로 가장 가까운 speaker가 매핑된다.
- speaker_role은 UNKNOWN으로 시작해도 된다.

#### 36.7 7단계: 언어 지표 계산

목표:

```text
utterance list
  -> MLU, NDW, NTW, TTR, latency 계산
```

완료 기준:

- speaker별 지표가 생성된다.
- CHILD role이 있으면 CHILD 기준 지표가 생성된다.
- role이 없으면 speaker별 지표를 모두 출력한다.

#### 36.8 8단계: RAG ingest

목표:

```text
문서 업로드
  -> chunk 생성
  -> embedding 생성
  -> pgvector 저장
```

완료 기준:

- 문서 1개 이상을 chunk로 나눌 수 있다.
- chunk metadata가 저장된다.
- 검색 가능한 embedding이 저장된다.

#### 36.9 9단계: RAG query

목표:

```text
질문 입력
  -> 관련 chunk top_k 반환
```

완료 기준:

- Kiwi로 키워드가 추출된다.
- ontology 기반 확장이 적용된다.
- top_k chunk가 score와 함께 반환된다.

#### 36.10 10단계: LLM report

목표:

```text
metrics + transcript summary + evidence
  -> SOAP Note draft JSON
```

완료 기준:

- JSON schema를 만족한다.
- evidence_chunk_ids가 포함된다.
- 치료사 검토 필요 문구가 포함된다.

#### 36.11 11단계: Worker 통합

목표:

```text
SQS 메시지 1개
  -> 전체 분석 완료
  -> S3/RDS 저장
```

완료 기준:

- Job 상태가 단계별로 업데이트된다.
- 실패 시 FAILED 상태와 error_code가 저장된다.
- 재시도 가능한 구조가 있다.

---

### 37. requirements.txt 초안

```txt
fastapi
uvicorn[standard]
pydantic
pydantic-settings

boto3
sqlalchemy
psycopg[binary]
pgvector

numpy
pandas

torch
torchaudio
transformers
accelerate
onnxruntime

pyannote.audio
kiwipiepy

python-dotenv
loguru
tenacity

ffmpeg-python
soundfile
librosa

pytest
pytest-asyncio
httpx
```

환경과 GPU 사용 여부에 따라 `torch` 설치 방식은 달라질 수 있습니다.  
CUDA 버전은 서버 환경에 맞춰 별도로 고정합니다.

---

### 38. Dockerfile 초안

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install -r requirements.txt

COPY app ./app

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

GPU Worker용 이미지는 CUDA base image를 별도로 두는 것을 권장합니다.

```text
CPU API/Worker Dockerfile
GPU Worker Dockerfile
```

이렇게 분리하면 이미지 크기와 배포 속도를 관리하기 쉽습니다.

---

### 39. .env.example 초안

```env
APP_ENV=local
LOG_LEVEL=INFO

HF_TOKEN=

AWS_REGION=ap-northeast-2

S3_BUCKET_UTTERAI_AUDIO=utterai-audio-dev
S3_BUCKET_UTTERAI_REPORT=utterai-report-dev
S3_BUCKET_UTTERAI_RAG=utterai-rag-dev

DATABASE_URL=postgresql+psycopg://utterai:utterai@localhost:5432/utterai_ai

SQS_AUDIO_PREPROCESS_QUEUE_URL=
SQS_GPU_INFERENCE_QUEUE_URL=
SQS_REPORT_ANALYSIS_QUEUE_URL=
SQS_RAG_INGEST_QUEUE_URL=

VAD_MODEL_NAME=onnx-community/silero-vad
DIARIZATION_MODEL_NAME=pyannote/speaker-diarization-3.1
ASR_MODEL_NAME=openai/whisper-large-v3-turbo
EMBEDDING_MODEL_NAME=nlpai-lab/KURE-v1
LLM_MODEL_NAME=LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct

MODEL_DEVICE=auto
ASR_DEVICE=cuda
DIARIZATION_DEVICE=cuda
LLM_DEVICE=cuda

RAG_TOP_K=5
RAG_SCORE_THRESHOLD=0.5
```

---

### 40. GitHub 작업 단위 추천

Utter_AI 레포에서 바로 작업할 때는 다음 순서로 branch를 나누면 관리하기 좋습니다.

| 브랜치 | 작업 |
| --- | --- |
| `feat/project-skeleton` | 기본 폴더, README, config, health API |
| `feat/model-wrappers` | VAD, ASR, Diarization wrapper |
| `feat/audio-pipeline` | 전처리, VAD, ASR, Diarization 연결 |
| `feat/utterance-alignment` | speaker + transcript 정렬 |
| `feat/language-metrics` | MLU, NDW, NTW, TTR 계산 |
| `feat/rag-ingestion` | 문서 파싱, chunk, embedding 저장 |
| `feat/rag-retrieval` | semantic layer, ontology, retriever |
| `feat/report-generation` | LLM 리포트 초안 생성 |
| `feat/worker-integration` | SQS Worker 통합 |
| `feat/dockerize-ai` | Dockerfile, 실행 스크립트 |

---

### 41. MVP 완료 기준

MVP 완료 기준은 모델 성능이 완벽한지가 아니라, **하나의 음성 파일이 들어와 끝까지 결과가 생성되는지**입니다.

완료 기준:

```text
1. 샘플 음성을 S3 또는 로컬 경로로 입력한다.
2. VAD 결과가 생성된다.
3. 화자 분리 결과가 생성된다.
4. STT 결과가 생성된다.
5. 발화 단위 JSON이 생성된다.
6. 언어 지표가 계산된다.
7. RAG 검색 결과가 생성된다.
8. SOAP Note 초안이 생성된다.
9. 결과가 S3/RDS 저장 형식으로 정리된다.
10. Backend가 job_id로 결과를 조회할 수 있는 형태가 된다.
```

---

### 42. 발표용 한 줄 정리

UtterAI의 AI 모듈은 Hugging Face 기반 VAD, 화자 분리, STT 모델을 조합해 세션 음성을 화자별 발화 데이터로 변환하고, Kiwi 기반 언어 지표 계산과 RAG 검색을 통해 치료사가 검토할 수 있는 SOAP Note 초안을 생성하는 비동기 AI 분석 파이프라인입니다.
