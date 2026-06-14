# 모델 로딩 가이드

UtterAI에서 사용하는 AI 모델은 **수동으로 파일을 다운로드할 필요가 없습니다.**
각 라이브러리(`transformers`, `sentence-transformers`, `pyannote.audio` 등)가
코드에서 `load()`를 호출하는 시점에 Hugging Face Hub에서 자동으로 다운로드하고
로컬 캐시에 저장합니다.

```
load() 첫 호출
  → Hugging Face Hub에서 모델 파일 다운로드
  → ~/.cache/huggingface/ 에 캐시 저장
  → 이후 호출은 캐시에서 바로 로드 (네트워크 불필요)
```

---

## 공통 사항

### 캐시 경로

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `HF_HOME` | `~/.cache/huggingface` | 모델 캐시 루트 경로 |
| `TRANSFORMERS_CACHE` | `HF_HOME/hub` | transformers 모델 저장 위치 |

캐시 경로를 변경하려면 `.env`에 추가합니다.

```env
HF_HOME=/mnt/models/.cache/huggingface
```

### 오프라인 실행

한 번 다운로드한 뒤에는 네트워크 없이 실행 가능합니다.

```env
TRANSFORMERS_OFFLINE=1
HF_DATASETS_OFFLINE=1
```

### Hugging Face 토큰

일부 모델(pyannote)은 gated model이라 토큰이 필요합니다.
`.env`에 아래 항목을 추가합니다.

```env
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## 모델별 상세

---

### 1. Silero VAD — `onnx-community/silero-vad`

**역할**: 음성 파일에서 말한 구간과 침묵 구간을 분리합니다.

**로딩 방식**: `huggingface_hub`로 ONNX 파일을 다운로드하고 `onnxruntime`으로 실행합니다.

```python
from huggingface_hub import hf_hub_download
import onnxruntime as ort

# 첫 호출 시 ONNX 파일 자동 다운로드 (~수 MB)
model_path = hf_hub_download("onnx-community/silero-vad", "silero_vad.onnx")
session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
```

**특징**
- GPU 불필요, CPU로 충분히 빠름
- ONNX 형식이라 `torch` 없이도 실행 가능
- 다운로드 크기: 약 2 MB

**gated 여부**: 없음 (토큰 불필요)

**구현 파일**: `app/models/vad_silero.py`

---

### 2. Whisper — `openai/whisper-large-v3-turbo`

**역할**: 음성 구간을 텍스트로 전사(STT)합니다.

**로딩 방식**: `transformers`의 `AutoModelForSpeechSeq2Seq`로 자동 다운로드합니다.

```python
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
import torch

# 첫 호출 시 모델 가중치 자동 다운로드 (~1.5 GB)
processor = AutoProcessor.from_pretrained("openai/whisper-large-v3-turbo")
model = AutoModelForSpeechSeq2Seq.from_pretrained(
    "openai/whisper-large-v3-turbo",
    torch_dtype=torch.float16,
    device_map="cuda",
)
```

**특징**
- GPU 강력 권장 (CPU로도 가능하나 매우 느림)
- `transformers`의 `pipeline("automatic-speech-recognition")` 으로도 사용 가능
- 다운로드 크기: 약 1.5 GB
- 한국어 지원 (`language="korean"` 지정)

**gated 여부**: 없음 (토큰 불필요)

**구현 파일**: `app/models/asr_whisper.py`

---

### 3. pyannote 화자 분리 — `pyannote/speaker-diarization-3.1`

**역할**: 음성에서 화자를 구분하고 각 화자의 발화 구간을 분리합니다.

**로딩 방식**: `pyannote.audio`의 `Pipeline.from_pretrained`로 자동 다운로드합니다.

```python
from pyannote.audio import Pipeline

# HF 토큰 필수 — gated model
pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    use_auth_token="hf_xxxxxxxx",
)
pipeline.to(torch.device("cuda"))
```

**⚠️ 사전 준비 필요 (gated model)**

1. [huggingface.co/pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) 접속
2. 로그인 후 **"Access repository"** 동의
3. 아래 모델도 동일하게 동의 필요:
   - `pyannote/segmentation-3.0`
   - `pyannote/embedding-3.1`
4. `.env`에 `HF_TOKEN` 설정

위 과정을 건너뛰면 `401 Unauthorized` 오류가 발생합니다.

**특징**
- GPU 강력 권장
- 다운로드 크기: 약 800 MB (의존 모델 포함)
- 출력: `SPEAKER_00`, `SPEAKER_01` 등 레이블 (역할 매핑은 별도 처리)

**구현 파일**: `app/models/diarization_pyannote.py`

---

### 4. KURE-v1 임베딩 — `nlpai-lab/KURE-v1`

**역할**: 한국어 텍스트를 1024차원 벡터로 변환합니다. RAG 문서 저장과 검색에 사용됩니다.

**로딩 방식**: `sentence-transformers`로 자동 다운로드합니다.

```python
from sentence_transformers import SentenceTransformer

# 첫 호출 시 자동 다운로드 (~500 MB)
model = SentenceTransformer("nlpai-lab/KURE-v1", device="cpu")
vectors = model.encode(["텍스트 예시"], normalize_embeddings=True)
```

**특징**
- CPU로 충분 (문서 수가 많으면 `cuda`로 변경)
- `normalize_embeddings=True`로 cosine similarity 최적화
- 다운로드 크기: 약 500 MB

**gated 여부**: 없음 (토큰 불필요)

**구현 파일**: `app/models/embedding_kure.py`

---

### 5. EXAONE LLM — `LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct`

**역할**: RAG 검색 근거와 언어 지표를 바탕으로 SOAP Note 초안을 생성합니다.

**로딩 방식**: `transformers`의 `AutoModelForCausalLM`으로 자동 다운로드합니다.

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

# 첫 호출 시 자동 다운로드 (~5 GB)
tokenizer = AutoTokenizer.from_pretrained("LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct")
model = AutoModelForCausalLM.from_pretrained(
    "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct",
    torch_dtype=torch.bfloat16,
    device_map="cuda",
)
```

**특징**
- GPU 강력 권장 (2.4B 파라미터, bfloat16 기준 약 5 GB VRAM)
- CPU 실행 가능하나 응답 생성에 수 분 소요
- `apply_chat_template`으로 instruct 포맷 자동 적용
- 다운로드 크기: 약 5 GB

**gated 여부**: 없음 (토큰 불필요)

**구현 파일**: `app/models/llm_exaone.py`

---

## 전체 다운로드 크기 요약

| 모델 | 크기 | GPU 필요 | 토큰 필요 |
|---|---|---|---|
| Silero VAD | ~2 MB | 불필요 | 불필요 |
| Whisper large-v3-turbo | ~1.5 GB | 권장 | 불필요 |
| pyannote speaker-diarization-3.1 | ~800 MB | 권장 | **필요** |
| KURE-v1 | ~500 MB | 불필요 | 불필요 |
| EXAONE-3.5-2.4B-Instruct | ~5 GB | 권장 | 불필요 |
| **합계** | **~8 GB** | | |

---

## Worker별 모델 분리 배포 전략

모든 모델을 하나의 Worker에서 로드하면 메모리가 부족할 수 있습니다.
CPU Worker와 GPU Worker를 분리해 배포합니다.

| Worker | 담당 모델 | 실행 환경 |
|---|---|---|
| CPU Worker | Silero VAD, KURE-v1, Kiwi, 언어 지표 계산 | ECS Fargate (CPU) |
| GPU Worker | Whisper, pyannote, EXAONE | EKS GPU Node / GPU EC2 |

---

## 로컬 개발 시 빠른 시작

처음 실행할 때 모델이 자동으로 다운로드됩니다.
pyannote만 사전 준비가 필요합니다.

```bash
# 1. 환경 변수 설정
cp .env.example .env
# .env 에 HF_TOKEN 입력

# 2. 의존성 설치 (uv)
uv sync --extra cpu

# 3. API 실행 (모델은 첫 요청 시 자동 다운로드)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```
