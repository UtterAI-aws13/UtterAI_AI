# KURE-v1 검색 Lambda (AgentCore Gateway → Lambda → KURE-v1 임베딩 → pgvector 검색)
# 빌드 컨텍스트는 반드시 레포 루트여야 한다 (app/, pyproject.toml, uv.lock 참조).
#
#   docker build -f lambda/kure_retriever/Dockerfile -t utterai-kure-retriever:latest .
#
# KURE-v1 모델은 빌드 타임에 이미지에 베이킹한다. Lambda가 private subnet에서
# 30초 timeout으로 동작하므로 콜드스타트마다 HuggingFace에서 내려받지 않는다.

FROM public.ecr.aws/lambda/python:3.11 AS builder

RUN pip install --no-cache-dir uv

WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --extra cpu --format requirements-txt --output-file requirements.txt \
    && pip install --no-cache-dir -r requirements.txt --target /opt/python-deps

ENV HF_HOME=/opt/hf_cache
ENV PYTHONPATH=/opt/python-deps
RUN python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('nlpai-lab/KURE-v1')"

FROM public.ecr.aws/lambda/python:3.11

COPY --from=builder /opt/python-deps ${LAMBDA_TASK_ROOT}
COPY --from=builder /opt/hf_cache /opt/hf_cache
COPY app ${LAMBDA_TASK_ROOT}/app
COPY lambda/kure_retriever/handler.py ${LAMBDA_TASK_ROOT}/handler.py

# 베이킹된 캐시만 사용하고 런타임 네트워크 다운로드는 막는다.
ENV HF_HOME=/opt/hf_cache
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1

CMD ["handler.lambda_handler"]
