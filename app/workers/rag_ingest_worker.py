def handle_ingest_message(message: dict) -> None:
    # TODO: 문서 S3 다운로드 -> 파싱 -> chunk -> 임베딩 -> pgvector 저장
    raise NotImplementedError


def start_worker() -> None:
    # TODO: SQS 폴링 루프
    raise NotImplementedError
