# KURE-v1 검색 Lambda (AgentCore Gateway → Lambda → KURE-v1 임베딩 → pgvector 검색)
# 빌드 컨텍스트는 반드시 레포 루트여야 한다 (app/, pyproject.toml, uv.lock 참조).
#
#   docker build -f lambda/kure_retriever/Dockerfile -t utterai-kure-retriever:latest .
#
# KURE-v1 모델은 빌드 타임에 이미지에 베이킹한다. Lambda가 private subnet에서
# 30초 timeout으로 동작하므로 콜드스타트마다 HuggingFace에서 내려받지 않는다.
#
# python:3.11(Amazon Linux 2, glibc 2.26) 대신 3.12(Amazon Linux 2023, glibc 2.34)를
# 쓴다 - numpy 2.3+는 glibc 2.28 이상을 요구하는 manylinux wheel만 배포해서,
# AL2에서는 wheel을 못 찾고 소스 빌드로 빠지는데 이 이미지엔 컴파일러가 없어 실패한다.

FROM public.ecr.aws/lambda/python:3.12 AS builder

RUN pip install --no-cache-dir uv

WORKDIR /build
COPY pyproject.toml uv.lock ./
# uv export + 순정 pip install --target을 쓰면 pip이 --require-hashes 모드로
# 들어가는데, torch가 빌드 시점에 끌어오는 setuptools가 requirements.txt에
# 해시 고정돼 있지 않아 실패한다 (uv export는 런타임 의존성만 해시 고정하고
# PEP 517 빌드 의존성까지는 고정하지 않는다). uv pip install은 이 경우를
# 정상 처리한다.
RUN uv pip install --target /opt/python-deps \
    -r <(uv export --frozen --no-dev --extra cpu --format requirements-txt)

ENV HF_HOME=/opt/hf_cache
ENV PYTHONPATH=/opt/python-deps
RUN python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('nlpai-lab/KURE-v1')"

FROM public.ecr.aws/lambda/python:3.12

COPY --from=builder /opt/python-deps ${LAMBDA_TASK_ROOT}
COPY --from=builder /opt/hf_cache /opt/hf_cache
COPY app ${LAMBDA_TASK_ROOT}/app
COPY lambda/kure_retriever/handler.py ${LAMBDA_TASK_ROOT}/handler.py

# 베이킹된 캐시만 사용하고 런타임 네트워크 다운로드는 막는다.
ENV HF_HOME=/opt/hf_cache
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1

CMD ["handler.lambda_handler"]
