# 코드 흐름 상세 가이드

각 `.py` 파일이 어떤 순서로 호출되고, 무엇을 입력받아 무엇을 반환하는지 설명합니다.

---

## 전체 호출 순서 한눈에 보기

```
analysis_worker.py          SQS 메시지 수신
  └─ analysis_pipeline.py   전체 파이프라인 진입점
       ├─ audio_preprocess.py      음성 파일 표준화
       ├─ models/vad_silero.py     말소리 구간 추출
       ├─ models/diarization_pyannote.py   화자 분리
       ├─ models/asr_whisper.py    음성 → 텍스트
       ├─ pipelines/alignment.py   세 결과 병합 → Utterance
       │    └─ (내부) Kiwi 형태소 분석
       ├─ pipelines/metrics_pipeline.py   언어 지표 계산
       │    ├─ metrics/mlu.py
       │    ├─ metrics/lexical_diversity.py
       │    └─ metrics/response_latency.py
       ├─ rag/retriever.py         RAG 문서 검색
       │    └─ rag/rag_graph.py    LangGraph 실행
       │         ├─ rag/semantic_layer.py
       │         ├─ models/embedding_kure.py
       │         └─ rag/vector_store.py
       └─ pipelines/report_pipeline.py    리포트 생성
            ├─ rag/prompt_templates.py
            └─ models/llm_exaone.py
```

---

## 1. `app/workers/analysis_worker.py`

**역할**: SQS 큐를 폴링하다가 메시지가 오면 파이프라인을 시작합니다.

```python
def start_worker():
    # SQS long polling (20초 대기)
    # 메시지 수신 시 handle_message() 호출
    ...

def handle_message(message: dict):
    job = JobMessage(**message)   # dict → JobMessage 스키마로 변환
    run_analysis(job)             # analysis_pipeline으로 넘김
```

**받는 SQS 메시지 구조** (`schemas/job.py` → `JobMessage`):
```json
{
  "job_id": "job_abc123",
  "session_id": "session_001",
  "s3_audio_key": "audio/session_001/original.m4a",
  "options": { "language": "ko" }
}
```

---

## 2. `app/pipelines/analysis_pipeline.py`

**역할**: 전체 단계를 순서대로 호출하는 오케스트레이터입니다. 각 단계 진입 시 Job 상태를 RDS에 업데이트합니다.

```python
def run_analysis(message: JobMessage):
    # 1. 음성 전처리
    audio_meta = preprocess_audio(s3_path, local_path)

    # 2. VAD
    speech_segments = vad_model.predict(local_wav_path)

    # 3. 화자 분리
    speaker_segments = pyannote_model.predict(local_wav_path)

    # 4. STT
    asr_result = whisper_model.predict(local_wav_path)

    # 5. 발화 정렬
    utterances = align_segments(speech_segments, speaker_segments, asr_result.segments)

    # 6. 언어 지표
    metrics = calculate_metrics(utterances, message.session_id)

    # 7. RAG 검색
    rag_result = await retriever.retrieve(RagQuery(question=...))

    # 8. 리포트 생성
    report = generate_report(job_id, session_id, utterances, metrics, rag_result, llm)

    # 9. S3 + RDS 저장
    ...
```

---

## 3. `app/pipelines/audio_preprocess.py`

**역할**: 어떤 포맷의 음성 파일이 들어와도 AI 모델이 공통으로 받을 수 있는 표준 포맷으로 변환합니다.

```python
def preprocess_audio(input_path: str, output_path: str) -> AudioMetadata:
    # ffmpeg 실행: 어떤 포맷이든 → 16kHz, mono, WAV
    # duration 측정
    # 반환: AudioMetadata
```

**입력**: S3에서 내려받은 원본 파일 (`.m4a`, `.mp3`, `.wav` 등)

**출력** (`schemas/audio.py` → `AudioMetadata`):
```python
AudioMetadata(
    file_path="./tmp/session_001.wav",
    duration_sec=342.5,
    sample_rate=16000,
    channels=1,
)
```

**왜 이 변환이 필요한가**: VAD, pyannote, Whisper 모두 16kHz mono WAV를 기준으로 설계돼 있습니다. 사전에 통일해두면 각 모델이 포맷 변환을 개별적으로 처리할 필요가 없습니다.

---

## 4. `app/models/vad_silero.py`

**역할**: 음성 파일 전체에서 사람이 말한 구간과 침묵 구간을 분리합니다.

```python
class SileroVADWrapper:
    def load(self):
        # HF Hub에서 silero_vad.onnx 다운로드
        # ONNX Runtime 세션 초기화

    def predict(self, audio_path: str) -> list[SpeechSegment]:
        # WAV 파일 읽기
        # ONNX 모델로 프레임 단위 음성 확률 계산
        # threshold(0.5) 이상인 구간을 묶어서 SpeechSegment 생성
        # 반환: SpeechSegment 목록
```

**출력** (`schemas/segment.py` → `SpeechSegment`):
```python
[
    SpeechSegment(segment_id="vad_000", start_time=1.2, end_time=3.5, confidence=0.97),
    SpeechSegment(segment_id="vad_001", start_time=5.1, end_time=8.3, confidence=0.99),
]
```

**왜 먼저 실행하는가**: 침묵 구간까지 포함해서 pyannote나 Whisper를 돌리면 처리 시간과 비용이 낭비됩니다. VAD가 먼저 말소리 구간만 추려내면 이후 모델의 입력 크기가 줄어듭니다.

---

## 5. `app/models/diarization_pyannote.py`

**역할**: 음성에서 화자를 구분하고 각 화자가 언제 말했는지 시간 구간을 반환합니다.

```python
class PyannoteWrapper:
    def load(self):
        # pyannote.audio Pipeline.from_pretrained() 호출
        # HF 토큰 필요 (gated model)
        # GPU로 이동

    def predict(self, audio_path: str) -> list[SpeakerSegment]:
        # pyannote pipeline 실행
        # 결과를 SpeakerSegment 목록으로 변환
```

**출력** (`schemas/segment.py` → `SpeakerSegment`):
```python
[
    SpeakerSegment(speaker_segment_id="spk_000", speaker_id="SPEAKER_00", speaker_role="UNKNOWN", start_time=1.2, end_time=3.5),
    SpeakerSegment(speaker_segment_id="spk_001", speaker_id="SPEAKER_01", speaker_role="UNKNOWN", start_time=4.0, end_time=6.2),
]
```

`speaker_role`은 이 단계에서 항상 `UNKNOWN`입니다. SPEAKER_00이 치료사인지 아동인지는 alignment 이후에 결정됩니다.

---

## 6. `app/models/asr_whisper.py`

**역할**: 음성 파일을 텍스트로 전사하고, 각 구간의 시작/끝 timestamp를 함께 반환합니다.

```python
class WhisperASRWrapper:
    def load(self):
        # transformers AutoModelForSpeechSeq2Seq 로드
        # 또는 faster-whisper 로드

    def predict(self, audio_path: str) -> ASRResult:
        # language="ko" 고정
        # 전사 실행
        # segment별 timestamp 포함해서 반환
```

**출력** (`schemas/segment.py` → `ASRResult`):
```python
ASRResult(
    text="엄마 이거 봐 어디 봐볼까 ...",
    segments=[
        ASRSegment(asr_segment_id="asr_000", start_time=1.2, end_time=3.5, text="엄마 이거 봐", confidence=0.91),
        ASRSegment(asr_segment_id="asr_001", start_time=4.0, end_time=6.2, text="어디 봐볼까", confidence=0.88),
    ]
)
```

timestamp가 없으면 화자 분리 결과와 매칭이 불가능하기 때문에 segment 단위 결과가 필수입니다.

---

## 7. `app/pipelines/alignment.py`

**역할**: VAD / 화자 분리 / STT 세 결과를 시간 기준으로 합쳐 최종 발화 단위인 `Utterance`를 만듭니다. 내부에서 Kiwi 형태소 분석도 실행합니다.

```python
def align_segments(speech_segments, speaker_segments, asr_segments) -> list[Utterance]:
    for asr in sorted(asr_segments, by=start_time):

        # 이 ASR 구간과 가장 많이 시간이 겹치는 화자 선택
        best_speaker = max(speaker_segments, key=overlap_with(asr))

        # Kiwi 형태소 분석
        morphemes, tokens = _analyze_text(asr.text)
        # morphemes: [엄마/NNG, 이거/NP, 봐/VV]  → MLU 계산에 사용
        # tokens:    ["엄마", "이거", "봐"]        → NTW/NDW/TTR 계산에 사용

        Utterance(
            speaker_id=best_speaker.speaker_id,
            speaker_role=best_speaker.speaker_role,
            text=asr.text,
            morphemes=morphemes,
            tokens=tokens,
            ...
        )
```

**입력**: `list[SpeechSegment]` + `list[SpeakerSegment]` + `list[ASRSegment]`

**출력** (`schemas/transcript.py` → `Utterance`):
```python
[
    Utterance(
        utterance_id="utt_asr_000",
        speaker_id="SPEAKER_00",
        speaker_role="UNKNOWN",
        start_time=1.2, end_time=3.5,
        text="엄마 이거 봐",
        morphemes=[Morpheme(form="엄마", tag="NNG"), ...],
        tokens=["엄마", "이거", "봐"],
    ),
    ...
]
```

---

## 8. `app/pipelines/metrics_pipeline.py`

**역할**: Utterance 목록을 화자별로 묶어 언어 지표를 계산합니다.

```python
def calculate_metrics(utterances, session_id) -> list[SpeakerMetrics]:
    sorted_utts = sorted(utterances, by=start_time)

    # 전체 발화로 THERAPIST→CHILD 반응 지연 시간 1회 계산
    global_latency = response_latency.calculate_average_response_latency(sorted_utts)

    # 화자별로 그룹핑
    for speaker_id, utts in group_by_speaker(sorted_utts):
        mlu_val     = mlu.calculate_mlu(utts)           # metrics/mlu.py
        ntw_val     = lexical_diversity.calculate_ntw(utts)  # metrics/lexical_diversity.py
        ndw_val     = lexical_diversity.calculate_ndw(utts)
        ttr_val     = lexical_diversity.calculate_ttr(utts)

        # response_latency는 CHILD 화자에게만 포함
        latency = global_latency if speaker_role == "CHILD" else None

        SpeakerMetrics(speaker_id, speaker_role, LanguageMetrics(...))
```

**내부에서 호출하는 파일들**:

| 파일 | 함수 | 계산 내용 |
|---|---|---|
| `metrics/mlu.py` | `calculate_mlu()` | 전체 형태소 수 / 전체 발화 수 |
| `metrics/lexical_diversity.py` | `calculate_ntw()` | 총 토큰 수 (중복 포함) |
| `metrics/lexical_diversity.py` | `calculate_ndw()` | 고유 토큰 수 |
| `metrics/lexical_diversity.py` | `calculate_ttr()` | NDW / NTW |
| `metrics/response_latency.py` | `calculate_average_response_latency()` | THERAPIST 끝 → CHILD 시작 평균 간격 |

**출력** (`schemas/metrics.py` → `SpeakerMetrics`):
```python
[
    SpeakerMetrics(
        speaker_id="SPEAKER_00",
        speaker_role="UNKNOWN",
        metrics=LanguageMetrics(
            mlu_morpheme=3.8, ntw=142, ndw=76, ttr=0.535,
            average_response_latency_sec=None,
        )
    ),
]
```

---

## 9. `app/rag/retriever.py` → `app/rag/rag_graph.py`

**역할**: LangGraph 그래프를 실행해 관련 문서 청크를 검색합니다. LLM 호출 없음.

```python
# retriever.py
class Retriever:
    def __init__(self, vector_store, embedding_model, top_k, score_threshold):
        self._graph = build_rag_graph(...)   # rag_graph.py에서 그래프 조립

    async def retrieve(self, query: RagQuery) -> RagResult:
        initial_state = { "question": ..., "retry_count": 0, ... }
        final_state = await self._graph.ainvoke(initial_state)
        return final_state["rag_result"]
```

**`rag_graph.py` 내부 LangGraph 노드 실행 순서**:

```
[node] extract_keywords
  Kiwi.tokenize(question)
  명사(NNG/NNP) + 동사(VV) + 형용사(VA) 추출
  → kiwi_keywords: ["MLU", "발화", "중재"]

[node] expand_query
  rag/semantic_layer.py: expand_query(kiwi_keywords)
    ontology.yaml 참조 → 관련어 확장
    예) MLU → ["평균 발화 길이", "형태소 수", "발화 복잡도"]
  rag/semantic_layer.py: get_metadata_filters(kiwi_keywords)
    → filters: { language_area: ["expressive_language"] }

[node] retrieve
  embedding_kure.predict([question + expanded_keywords])
    → query_vector: [0.12, -0.34, ..., 0.08]  (1024차원)
  vector_store.search(query_vector, filters, top_k=5)
    → pgvector cosine_distance() → 상위 결과 반환

[조건 분기]
  score >= 0.5 청크가 2개 이상 → finalize
  부족하면     → fallback_retrieve (필터 제거, top_k=10)

[node] finalize
  score 통과한 청크만 모아 RagResult 생성
```

**`rag/vector_store.py`에서 실제 검색 쿼리**:
```python
distance_col = RagChunkORM.embedding.cosine_distance(embedding)
score_col = (1 - distance_col).label("score")
stmt = select(RagChunkORM, score_col).order_by(distance_col).limit(top_k * 3)
```

**출력** (`schemas/rag.py` → `RagResult`):
```python
RagResult(
    query="MLU가 낮은 아동의 표현언어 중재 방법은?",
    expanded_query=["MLU", "평균 발화 길이", "표현언어", ...],
    evidence=[
        RagEvidence(chunk_id="doc_001_chunk_0014", title="언어발달 평가 가이드",
                    score=0.82, text="만 4세 아동의 MLU 기준값은..."),
        RagEvidence(chunk_id="doc_003_chunk_0007", title="언어중재 활동 매뉴얼",
                    score=0.74, text="표현언어 지연 아동을 위한 활동으로..."),
    ]
)
```

---

## 10. `app/pipelines/report_pipeline.py`

**역할**: RAG 근거와 언어 지표를 EXAONE에 입력해 SOAP Note 초안을 생성합니다. 유일한 LLM 호출 지점입니다.

```python
def generate_report(job_id, session_id, utterances, metrics, rag_result, llm) -> ReportDraft:

    # 1. 프롬프트 조립 (rag/prompt_templates.py)
    prompt = build_report_prompt(utterances, metrics, rag_result)
    # 프롬프트 포함 내용:
    #   - 화자별 MLU / NTW / NDW / TTR 수치
    #   - 대표 발화 최대 10개 (전체 전사문 노출 방지)
    #   - RAG 근거 청크 (앞 200자)
    #   - 출력 JSON 스키마
    #   - 안전 지침 (진단 확정 금지, 근거 외 단정 금지)

    # 2. EXAONE 호출 (models/llm_exaone.py)
    raw = llm.predict(prompt)
    # → EXAONE이 JSON 문자열 반환

    # 3. JSON 파싱 (최대 3회 retry)
    #   1차: json.loads(raw) 직접 시도
    #   2차: ```json ... ``` 마크다운 블록에서 추출
    #   3차: 텍스트에서 첫 번째 { ... } 블록 추출
    data = _extract_json(raw)

    # 4. 필수 필드 누락 시 빈 문자열로 채움 (schema repair)
    data = _repair_schema(data)

    # 5. ReportDraft 생성
    return ReportDraft(soap_note=SOAPNote(**data["soap_note"]), ...)
```

**`rag/prompt_templates.py`가 만드는 프롬프트 구조**:
```
[시스템 지침]
  진단 확정 금지 / 근거 문서 밖 내용 단정 금지 / JSON 출력 필수

[언어 지표]
  SPEAKER_00: MLU=3.8, NTW=142, NDW=76, TTR=0.535

[대표 발화 최대 10개]
  SPEAKER_00: 엄마 이거 봐
  SPEAKER_01: 어디 봐볼까

[검색 근거]
  [doc_001_chunk_0014] 언어발달 평가 가이드: 만 4세 아동의 MLU 기준값은...

[출력 형식]
  { "soap_note": { "subjective": ..., "objective": ..., ... } }
```

**`models/llm_exaone.py` 내부 처리**:
```python
def predict(self, prompt: str) -> str:
    messages = [{"role": "user", "content": prompt}]
    input_ids = tokenizer.apply_chat_template(messages, return_tensors="pt")
    output_ids = model.generate(input_ids, max_new_tokens=1024, do_sample=False)
    generated = output_ids[0][input_ids.shape[-1]:]   # 입력 제외, 생성 부분만
    return tokenizer.decode(generated, skip_special_tokens=True)
```

**출력** (`schemas/report.py` → `ReportDraft`):
```python
ReportDraft(
    report_id="uuid-...",
    job_id="job_abc123",
    session_id="session_001",
    model_versions=ModelVersions(llm="LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct", ...),
    soap_note=SOAPNote(
        subjective="보호자 보고에 따르면 가정에서 단어 조합이 증가하는 추세",
        objective="MLU 3.8, TTR 0.535, 평균 반응 지연 1.4초",
        assessment="또래 대비 표현언어 발달 지연 소견 (근거: doc_001_chunk_0014)",
        plan="다음 회기에서 3어절 문장 산출 촉진 활동 적용 권장",
    ),
    clinical_flags=[ClinicalFlag(type="LOW_TTR", description="어휘 다양도 낮음", ...)],
    requires_human_review=True,
)
```

---

## 11. RAG Ingest 흐름 (별도 경로)

분석 파이프라인과 별개로, 치료 문서를 DB에 저장하는 흐름입니다.

```
POST /ai/rag/ingest
  └─ rag_ingest_worker.py  (또는 API에서 직접 호출)
       └─ rag/ingest.py: ingest_document()
            ├─ _extract_text()          TXT/PDF → 텍스트 추출
            ├─ chunker.make_chunks()    300자 단위 청크 분할 (overlap 50자)
            │    └─ _split_sentences()  문장 끝 문자 기준 분리
            ├─ embedding_kure.predict() 청크 목록 → 1024차원 벡터 목록
            └─ vector_store.upsert()    pgvector rag_chunks 테이블에 저장
```

이 흐름이 먼저 실행돼야 `retriever.retrieve()`가 검색할 데이터가 존재합니다.

---

## 스키마 파일이 연결 고리 역할을 하는 구조

각 단계의 반환값은 `schemas/`에 정의된 Pydantic 모델입니다.
파일 간 데이터를 넘길 때 타입이 보장되고, 어느 단계에서 오류가 났는지 즉시 파악할 수 있습니다.

```
audio_preprocess  →  AudioMetadata          schemas/audio.py
vad_silero        →  list[SpeechSegment]    schemas/segment.py
diarization       →  list[SpeakerSegment]   schemas/segment.py
asr_whisper       →  ASRResult              schemas/segment.py
alignment         →  list[Utterance]        schemas/transcript.py
metrics_pipeline  →  list[SpeakerMetrics]   schemas/metrics.py
retriever         →  RagResult              schemas/rag.py
report_pipeline   →  ReportDraft            schemas/report.py
```
