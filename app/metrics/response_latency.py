# 반응 지연 시간(Response Latency) 계산
# 치료사 발화가 끝난 뒤 아동이 말을 시작하기까지 걸리는 시간의 평균
# 대화 상호작용 패턴 분석에 사용된다
from app.schemas import Utterance


def calculate_average_response_latency(utterances: list[Utterance]) -> float | None:
    """SLP → PATIENT 발화 전환 구간의 평균 간격(초)을 반환한다.

    다음 조건을 모두 만족하는 구간만 계산에 포함한다:
    - 이전 발화자가 SLP, 다음 발화자가 PATIENT
    - 두 발화 사이 간격이 0 이상 10초 이하 (비정상 값 제외)

    조건을 만족하는 구간이 없으면 None을 반환한다.
    """
    latencies = []
    for i in range(1, len(utterances)):
        prev = utterances[i - 1]
        curr = utterances[i]
        if prev.speaker_role == "SLP" and curr.speaker_role == "PATIENT":
            gap = curr.start_time - prev.end_time
            if 0 <= gap <= 10:  # 음수(겹침)나 10초 초과(다른 주제 전환)는 제외
                latencies.append(gap)
    if not latencies:
        return None
    return sum(latencies) / len(latencies)
