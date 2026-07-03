import json
import os


def _load_rds_secret() -> None:
    """Secrets Manager에서 RDS 자격증명을 읽어 환경 변수로 주입한다.

    Settings(pydantic)가 환경 변수를 읽기 전에 호출해야 하므로
    app 모듈 import 앞에 위치한다.
    """
    secret_arn = os.environ.get("RDS_SECRET_ARN")
    if not secret_arn:
        return
    import boto3
    secret_str = boto3.client("secretsmanager").get_secret_value(
        SecretId=secret_arn
    )["SecretString"]
    secret = json.loads(secret_str)
    os.environ.setdefault("DB_USER", secret.get("username", ""))
    os.environ.setdefault("DB_PASSWORD", secret.get("password", ""))


_load_rds_secret()

# app 모듈 import는 반드시 _load_rds_secret() 이후에 위치해야 한다.
# Settings가 모듈 로드 시점에 환경 변수를 읽기 때문이다.
#
# Evidence Research Agent(app.agents.report_generation.evidence_research.tools)의
# @tool 함수를 그대로 재사용한다 - @tool 데코레이터는 일반 함수 호출을 그대로
# 지원하므로(Strands Agent 없이도 호출 가능) 여기서 로직을 복제하지 않는다.
# Kiwi/ontology/필터/fallback 파이프라인은 이 모듈 하나에만 존재해야 한다.
from app.agents.report_generation.evidence_research.tools import (  # noqa: E402
    fetch_document_section,
    hybrid_search,
    rerank_evidence,
    resolve_ontology_synonyms,
    search_clinical_guidelines,
    search_international_evidence,
    search_korean_evidence,
)

# AgentCore Gateway가 여러 tool_schema를 이 Lambda 하나에 매핑할 때, 호출된
# tool 이름은 Lambda context에 "${target_name}_${tool_name}" 형식으로 실려온다
# (참고: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-tool-naming.html).
# target_name 접두어를 모르므로 접미어(tool_name) 일치로 판별한다.
_TOOL_DISPATCH = {
    "search_korean_evidence": lambda event: search_korean_evidence(
        query_ko=event["query_ko"], top_k=event.get("top_k", 10)
    ),
    "search_international_evidence": lambda event: search_international_evidence(
        query_en=event["query_en"], top_k=event.get("top_k", 10)
    ),
    "search_clinical_guidelines": lambda event: search_clinical_guidelines(
        query=event["query"], top_k=event.get("top_k", 10)
    ),
    "hybrid_search": lambda event: hybrid_search(
        query=event["query"], top_k=event.get("top_k", 10)
    ),
    "rerank_evidence": lambda event: rerank_evidence(
        candidates=event["candidates"], query=event["query"]
    ),
    "fetch_document_section": lambda event: fetch_document_section(
        chunk_id=event["chunk_id"]
    ),
    "resolve_ontology_synonyms": lambda event: resolve_ontology_synonyms(
        term=event["term"]
    ),
}


def _resolve_tool_name(context) -> str | None:
    client_context = getattr(context, "client_context", None)
    if client_context is None:
        return None
    custom = getattr(client_context, "custom", None) or {}
    return custom.get("bedrockAgentCoreToolName")


def lambda_handler(event: dict, context) -> dict:
    """AgentCore Gateway에서 호출되는 Evidence Research 검색 tool 진입점.

    하나의 Lambda가 7개 tool_schema(search_korean_evidence 등)를 전부
    처리한다 - Gateway target마다 별도 Lambda를 두지 않고, 호출된 tool 이름을
    context에서 읽어 분기한다.

    event: 호출된 tool의 입력 파라미터 (예: {"query_ko": "...", "top_k": 5}).
    """
    if event.get("query") == "ping" or event.get("query_ko") == "ping":
        return {"statusCode": 200, "body": json.dumps([])}

    full_tool_name = _resolve_tool_name(context) or ""
    handler_fn = next(
        (fn for name, fn in _TOOL_DISPATCH.items() if full_tool_name.endswith(name)),
        None,
    )
    if handler_fn is None:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": f"알 수 없는 tool: {full_tool_name!r}"}),
        }

    result = handler_fn(event)
    return {"statusCode": 200, "body": json.dumps(result, ensure_ascii=False)}
