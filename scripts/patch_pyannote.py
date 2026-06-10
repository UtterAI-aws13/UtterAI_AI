"""
pyannote.audio 3.x + huggingface_hub 0.22+ 호환성 패치.

pyannote.audio 3.x 는 내부적으로 hf_hub_download(use_auth_token=...) 를 호출하는데
huggingface_hub 0.22+ 는 use_auth_token 파라미터를 제거했다.
이 스크립트는 설치된 pyannote pipeline.py / model.py 에 호환 shim 을 추가한다.

Docker 빌드 시 uv sync 이후 한 번 실행한다.
이미 패치된 파일은 건드리지 않는다.
"""
import importlib.util
import sys
from pathlib import Path

ALREADY_PATCHED_MARKER = "huggingface_hub >= 1.0 removed use_auth_token"

# pipeline.py 패치: from_pretrained 시그니처 + shim + hf_hub_download 인자 교체
PIPELINE_PATCHES = [
    # 1. token 파라미터 추가 (use_auth_token 뒤에)
    (
        "        use_auth_token: Union[Text, None] = None,\n        cache_dir",
        "        use_auth_token: Union[Text, None] = None,\n        token: Union[Text, None] = None,\n        cache_dir",
    ),
    # 2. 호환 shim 삽입 (checkpoint_path = str(...) 직전)
    (
        "        checkpoint_path = str(checkpoint_path)",
        (
            "        # huggingface_hub >= 1.0 removed use_auth_token in favour of token\n"
            "        if token is None:\n"
            "            token = use_auth_token\n"
            "        use_auth_token = None\n"
            "\n"
            "        checkpoint_path = str(checkpoint_path)"
        ),
    ),
    # 3. hf_hub_download 인자 교체
    (
        "                    use_auth_token=use_auth_token,",
        "                    token=token,",
    ),
    # 4. params.setdefault 수정
    (
        'params.setdefault("use_auth_token", use_auth_token)',
        'params.setdefault("use_auth_token", token)',
    ),
]

# model.py 패치: 동일 패턴, checkpoint = str(checkpoint) 사용
MODEL_PATCHES = [
    (
        "        use_auth_token: Union[Text, None] = None,\n        cache_dir",
        "        use_auth_token: Union[Text, None] = None,\n        token: Union[Text, None] = None,\n        cache_dir",
    ),
    (
        "        checkpoint = str(checkpoint)",
        (
            "        # huggingface_hub >= 1.0 removed use_auth_token in favour of token\n"
            "        if token is None:\n"
            "            token = use_auth_token\n"
            "        use_auth_token = None\n"
            "\n"
            "        checkpoint = str(checkpoint)"
        ),
    ),
    (
        "                    use_auth_token=use_auth_token,",
        "                    token=token,",
    ),
]


def find_package_file(package: str, relative: str) -> Path:
    spec = importlib.util.find_spec(package)
    if spec is None or spec.origin is None:
        raise RuntimeError(f"패키지를 찾을 수 없음: {package}")
    pkg_root = Path(spec.origin).parent
    target = pkg_root / relative
    if not target.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없음: {target}")
    return target


def patch_file(path: Path, patches: list[tuple[str, str]]) -> None:
    text = path.read_text(encoding="utf-8")

    if ALREADY_PATCHED_MARKER in text:
        print(f"[patch_pyannote] 이미 패치됨, 건너뜀: {path}")
        return

    changed = False
    for old, new in patches:
        if old in text:
            text = text.replace(old, new, 1)
            changed = True
        else:
            print(f"[patch_pyannote] WARNING: 패턴을 찾지 못함 — 버전이 다를 수 있음\n  파일: {path}\n  패턴: {old[:60]!r}")

    if changed:
        path.write_text(text, encoding="utf-8")
        print(f"[patch_pyannote] 패치 완료: {path}")
    else:
        print(f"[patch_pyannote] 변경 없음: {path}")


def main() -> None:
    targets = [
        ("pyannote.audio", "core/pipeline.py", PIPELINE_PATCHES),
        ("pyannote.audio", "core/model.py", MODEL_PATCHES),
    ]
    failed = False
    for package, relative, patches in targets:
        try:
            path = find_package_file(package, relative)
            patch_file(path, patches)
        except Exception as exc:
            print(f"[patch_pyannote] ERROR {package}/{relative}: {exc}", file=sys.stderr)
            failed = True

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
