from app.schemas import AudioMetadata


def preprocess_audio(input_path: str, output_path: str) -> AudioMetadata:
    # TODO: ffmpeg로 16kHz mono WAV 변환, duration 측정
    raise NotImplementedError
