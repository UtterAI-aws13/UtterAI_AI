import asyncio
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
from app.rag.retriever import retrieve_evidence  # noqa: E402


def lambda_handler(event: dict, context) -> dict:
    """AgentCore Gateway에서 호출되는 KURE-v1 임베딩 검색 엔트리포인트.

    event 예시:
    {
        "query": "만 3세 MLU 2.1 표현언어 중재 방법",
        "top_k": 5
    }
    """
    query = event.get("query", "")
    top_k = event.get("top_k", 5)

    if not query or query == "ping":
        return {"statusCode": 200, "body": json.dumps([])}

    results = asyncio.run(
        retrieve_evidence(
            metrics={},
            session={},
            top_k=top_k,
            direct_query=query,
        )
    )

    return {
        "statusCode": 200,
        "body": json.dumps(results, ensure_ascii=False),
    }
