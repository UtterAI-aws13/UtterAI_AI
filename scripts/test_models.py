"""
VAD / 화자 분리 / ASR 3단계 단독 테스트 스크립트.
RAG, LLM, DB 없이 모델 출력만 확인한다.

사용법:
  python scripts/test_models.py --audio samples/utterai_test.mp3
  python scripts/test_models.py --audio samples/utterai_test.mp3 --skip-diarization
  python scripts/test_models.py --audio samples/utterai_test.mp3 --device cpu
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# 로컬 ffmpeg 바이너리를 PATH에 추가 (시스템 PATH에 없을 때 대비)
_ffmpeg_local = Path(__file__).parent.parent / "ffmpeg"
if _ffmpeg_local.exists():
    os.environ["PATH"] = str(_ffmpeg_local) + os.pathsep + os.environ.get("PATH", "")

from app.config import settings


def _header(step: str) -> None:
    print(f"\n{'=' * 55}")
    print(f"  {step}")
    print(f"{'=' * 55}")


def _ok(label: str, val: str = "") -> None:
    suffix = f"  →  {val}" if val else ""
    print(f"  [OK]  {label}{suffix}")


def _err(label: str, exc: Exception) -> None:
    print(f"  [ERR] {label}")
    print(f"        {type(exc).__name__}: {exc}")


def _preprocess(audio_path: str) -> str:
    """mp3/m4a 등을 16kHz mono WAV로 변환. 이미 WAV면 그대로 반환."""
    from pathlib import Path
    import tempfile

    if Path(audio_path).suffix.lower() == ".wav":
        return audio_path

    tmp_wav = tempfile.mktemp(suffix=".wav")
    try:
        from app.pipelines.audio_preprocess import preprocess_audio
        meta = preprocess_audio(audio_path, tmp_wav)
        print(f"  전처리 완료: duration={meta.duration_sec:.1f}s → {tmp_wav}")
        return tmp_wav
    except NotImplementedError:
        import subprocess
        subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", tmp_wav],
            check=True, capture_output=True,
        )
        print(f"  ffmpeg 변환 완료 → {tmp_wav}")
        return tmp_wav


def run_vad(wav_path: str, device: str) -> list:
    _header("1. Silero VAD")
    t0 = time.perf_counter()
    try:
        from app.models.vad_silero import SileroVADWrapper
        model = SileroVADWrapper(settings.vad_model_name)
        model.load()
        _ok("모델 로드 완료")

        segments = model.predict(wav_path)
        elapsed = time.perf_counter() - t0

        _ok("predict 완료", f"{len(segments)}개 구간  ({elapsed:.1f}s)")
        for s in segments[:10]:
            print(f"     [{s.segment_id}] {s.start_time:.2f}s ~ {s.end_time:.2f}s  "
                  f"dur={s.duration_sec:.2f}s  conf={s.confidence:.3f}")
        if len(segments) > 10:
            print(f"     ... 외 {len(segments) - 10}개")
        return segments

    except Exception as e:
        _err("SileroVAD", e)
        return []


def run_diarization(wav_path: str, device: str) -> list:
    _header("2. pyannote 화자 분리")
    t0 = time.perf_counter()
    try:
        if not settings.hf_token:
            print("  [SKIP] HF_TOKEN이 없습니다. .env에 HF_TOKEN을 설정하세요.")
            return []

        from app.models.diarization_pyannote import PyannoteWrapper
        model = PyannoteWrapper(
            settings.diarization_model_name,
            device=device,
            hf_token=settings.hf_token,
        )
        model.load()
        _ok("모델 로드 완료")

        segments = model.predict(wav_path)
        elapsed = time.perf_counter() - t0

        speakers = sorted({s.speaker_id for s in segments})
        _ok("predict 완료", f"{len(segments)}개 구간  화자={speakers}  ({elapsed:.1f}s)")
        for s in segments[:10]:
            print(f"     [{s.speaker_segment_id}] {s.speaker_id}  "
                  f"{s.start_time:.2f}s ~ {s.end_time:.2f}s")
        if len(segments) > 10:
            print(f"     ... 외 {len(segments) - 10}개")
        return segments

    except Exception as e:
        _err("PyannoteWrapper", e)
        return []


def run_asr(wav_path: str, device: str) -> object:
    _header("3. Whisper ASR")
    t0 = time.perf_counter()
    try:
        from app.models.asr_whisper import WhisperASRWrapper
        model = WhisperASRWrapper(settings.asr_model_name, device=device)
        model.load()
        _ok("모델 로드 완료")

        result = model.predict(wav_path)
        elapsed = time.perf_counter() - t0

        _ok("predict 완료", f"{len(result.segments)}개 구간  ({elapsed:.1f}s)")
        print(f"\n  전사 전문:\n  {result.text[:300]}{'...' if len(result.text) > 300 else ''}")
        print()
        for s in result.segments[:10]:
            print(f"     [{s.asr_segment_id}] {s.start_time:.2f}s ~ {s.end_time:.2f}s  "
                  f"'{s.text}'")
        if len(result.segments) > 10:
            print(f"     ... 외 {len(result.segments) - 10}개")
        return result

    except Exception as e:
        _err("WhisperASR", e)
        return None


def main():
    parser = argparse.ArgumentParser(description="VAD / 화자분리 / ASR 단독 테스트")
    parser.add_argument("--audio", required=True, help="오디오 파일 경로")
    parser.add_argument(
        "--device", default="cpu",
        help="모델 디바이스 (cpu / cuda, 기본값: cpu)",
    )
    parser.add_argument(
        "--skip-diarization", action="store_true",
        help="화자 분리 건너뜀 (HF_TOKEN 없을 때)",
    )
    args = parser.parse_args()

    print(f"\naudio  : {args.audio}")
    print(f"device : {args.device}")

    wav_path = _preprocess(args.audio)

    vad_segments = run_vad(wav_path, args.device)

    if args.skip_diarization:
        print("\n[SKIP] 화자 분리 건너뜀 (--skip-diarization)")
        speaker_segments = []
    else:
        speaker_segments = run_diarization(wav_path, args.device)

    asr_result = run_asr(wav_path, args.device)

    print(f"\n{'=' * 55}")
    print("  결과 요약")
    print(f"{'=' * 55}")
    print(f"  VAD          : {len(vad_segments)}개 구간")
    print(f"  화자 분리    : {len(speaker_segments)}개 구간")
    if asr_result:
        print(f"  ASR segments : {len(asr_result.segments)}개")
        print(f"  ASR 전문     : {len(asr_result.text)}자")
    else:
        print("  ASR          : 실패")
    print()


if __name__ == "__main__":
    main()
