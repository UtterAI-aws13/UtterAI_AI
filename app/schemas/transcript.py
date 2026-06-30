# 발화 단위(Utterance) 스키마
# VAD + 화자 분리 + STT 세 결과를 정렬(alignment)한 최종 산출물
from pydantic import BaseModel


class Morpheme(BaseModel):
    """Kiwi 형태소 분석기가 반환하는 형태소 단위.

    form: 형태소 표면형 (예: "강아지")
    tag: 품사 태그 (예: NNG=일반명사, JKS=주격조사, VV=동사)
    MLU 계산과 RAG 쿼리 확장에 모두 사용된다.
    """
    form: str
    tag: str


class UtteranceSource(BaseModel):
    """발화가 어떤 원본 segment들로부터 생성됐는지 추적하는 참조 정보.

    디버깅 및 재분석 시 원본 VAD/화자/STT 구간으로 역추적할 수 있다.
    """
    vad_segment_id: str | None = None
    speaker_segment_id: str | None = None
    asr_segment_id: str | None = None


class Utterance(BaseModel):
    """파이프라인의 핵심 출력 단위. 누가(speaker) 언제(start/end) 무슨 말을(text) 했는지를 담는다.

    alignment 단계에서 ASRSegment에 가장 많이 겹치는 SpeakerSegment를 선택해 생성된다.
    morphemes는 Kiwi 분석 후 채워지며, MLU 계산에 사용된다.
    tokens는 공백 기준 단어 목록으로, NTW/NDW/TTR 계산에 사용된다.
    """
    utterance_id: str
    speaker_id: str
    speaker_role: str        # SpeakerRole 상수값
    start_time: float
    end_time: float
    duration_sec: float
    text: str
    asr_confidence: float
    morphemes: list[Morpheme] = []
    tokens: list[str] = []
    source: UtteranceSource | None = None
    target_text: str | None = None   # SLP가 제시한 목표 발화 — PCC 계산에 필요
