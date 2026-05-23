from app.schemas import Utterance


def calculate_average_response_latency(utterances: list[Utterance]) -> float | None:
    """THERAPIST 발화 end → CHILD 발화 start 간격의 평균"""
    latencies = []
    for i in range(1, len(utterances)):
        prev = utterances[i - 1]
        curr = utterances[i]
        if prev.speaker_role == "THERAPIST" and curr.speaker_role == "CHILD":
            gap = curr.start_time - prev.end_time
            if 0 <= gap <= 10:
                latencies.append(gap)
    if not latencies:
        return None
    return sum(latencies) / len(latencies)
