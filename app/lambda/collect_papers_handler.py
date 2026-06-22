"""
논문 수집 Lambda 핸들러.

EventBridge 월 1회 트리거 → PubMed + Semantic Scholar 수집
→ S3 저장 → SQS rag-ingest-queue 발행 → batch worker가 pgvector 인제스트.

외부 의존성 없음 (urllib + boto3만 사용). Lambda 런타임에 기본 포함.

S3 상태 파일:
  state/seen_dois.json          — 수집한 DOI 중복 방지
  state/paper_metadata.json     — 논문별 메타데이터 (ingest_rag_docs 참조용)
  documents/<doc_id>__<title>.txt — 논문 초록 txt
"""
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import date
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

# ── 환경 설정 (Lambda 환경변수) ─────────────────────────────────────────────

SECRET_ID = os.environ["SECRET_ID"]
S3_BUCKET = os.environ["S3_BUCKET_RAG"]
SQS_QUEUE_URL = os.environ["SQS_RAG_INGEST_QUEUE_URL"]
AWS_REGION = os.environ.get("AWS_REGION_NAME", "ap-northeast-2")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "ap-northeast-2")
BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_PAPER_MODEL_ID",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
)
PAPERS_LIMIT = int(os.environ.get("PAPERS_LIMIT", "20"))

S3_SEEN_DOIS_KEY = "state/seen_dois.json"
S3_PAPER_METADATA_KEY = "state/paper_metadata.json"
S3_DOCUMENTS_PREFIX = "documents"

PUBMED_QUERIES = [
    "Korean children language disorder speech language pathology",
    "Korean MLU mean length utterance language development children",
    "stuttering Korean children adults intervention",
    "aphasia Korean adults assessment rehabilitation",
    "Korean phonological disorder articulation children",
    "developmental language disorder Korean DLD",
    "Korean speech language pathology school age reading",
]

SEMANTIC_SCHOLAR_QUERIES = [
    "Korean children language disorder speech therapy",
    "MLU Korean language sample analysis morpheme",
    "Korean stuttering fluency intervention",
    "Korean aphasia assessment CIU discourse",
    "DLD developmental language disorder Korean",
]

_METADATA_PROMPT = """\
다음 언어재활 관련 논문의 제목과 초록을 읽고, JSON 형식으로 메타데이터를 추출하세요.

제목: {title}

초록: {abstract}

아래 필드를 추출하고 JSON만 출력하세요.

age_group (하나만 선택): "preschool" | "school_age" | "adult" | "all"
language_area (배열): expressive_language, receptive_language, phonology, morphosyntax,
  vocabulary, pragmatics, fluency, narrative_discourse, motor_speech,
  cognitive_communication, functional_communication, clinical_documentation
metric (배열, 없으면 빈 배열): mlu_morpheme, mlu_word, ndw, ntw, ttr, pcc, ciu_count, ciu_ratio, percent_ss, llu_morpheme
clinical_task (배열): assessment, intervention, report_generation, goal_writing

예시: {{"age_group": "preschool", "language_area": ["expressive_language", "morphosyntax"], "metric": ["mlu_morpheme"], "clinical_task": ["assessment"]}}
"""

_TRANSLATE_PROMPT = """\
다음 언어재활 논문의 제목과 영어 초록을 한국어로 번역하세요.
전문 임상 용어(MLU, PCC, CIU, DLD 등 약어)는 그대로 유지하세요.
번역문만 출력하고 다른 설명은 쓰지 마세요.

제목: {title}

영어 초록:
{abstract}
"""


# ── AWS 클라이언트 ────────────────────────────────────────────────────────────

def _get_secrets() -> dict:
    client = boto3.client("secretsmanager", region_name=AWS_REGION)
    resp = client.get_secret_value(SecretId=SECRET_ID)
    return json.loads(resp["SecretString"])


def _s3_get_json(key: str, default) -> object:
    s3 = boto3.client("s3", region_name=AWS_REGION)
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=key)
        return json.loads(resp["Body"].read())
    except s3.exceptions.NoSuchKey:
        return default
    except Exception:
        return default


def _s3_put_json(key: str, data) -> None:
    s3 = boto3.client("s3", region_name=AWS_REGION)
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(data, ensure_ascii=False, indent=2).encode(),
        ContentType="application/json",
    )


def _s3_put_text(key: str, text: str) -> None:
    s3 = boto3.client("s3", region_name=AWS_REGION)
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=text.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )


def _sqs_send(message: dict) -> None:
    sqs = boto3.client("sqs", region_name=AWS_REGION)
    sqs.send_message(QueueUrl=SQS_QUEUE_URL, MessageBody=json.dumps(message))


# ── HTTP 유틸 ─────────────────────────────────────────────────────────────────

def _http_get(url: str, params: dict | None = None, headers: dict | None = None, timeout: int = 20) -> bytes:
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url, headers=headers or {})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ── DOI 정규화 ────────────────────────────────────────────────────────────────

def normalize_doi(doi: str) -> str:
    return doi.lower().strip().removeprefix("https://doi.org/").removeprefix("http://doi.org/")


def doi_to_doc_id(doi: str) -> str:
    safe = re.sub(r"[^a-z0-9]", "_", normalize_doi(doi))
    return f"doc_paper_{safe}"


def _safe_filename(text: str, max_len: int = 40) -> str:
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:max_len]


# ── PubMed ────────────────────────────────────────────────────────────────────

def fetch_pubmed(queries: list[str], limit: int, email: str, api_key: str) -> list[dict]:
    if not email:
        log.warning("PUBMED_EMAIL 미설정 — PubMed 건너뜀")
        return []

    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    results: list[dict] = []
    seen_pmids: set[str] = set()

    for query in queries:
        try:
            params = {"db": "pubmed", "term": query, "retmode": "json", "retmax": limit, "email": email}
            if api_key:
                params["api_key"] = api_key

            data = json.loads(_http_get(f"{base}/esearch.fcgi", params))
            pmids = data.get("esearchresult", {}).get("idlist", [])
            new_pmids = [p for p in pmids if p not in seen_pmids]
            seen_pmids.update(new_pmids)
            if not new_pmids:
                continue

            time.sleep(0.4)
            xml_data = _http_get(
                f"{base}/efetch.fcgi",
                {"db": "pubmed", "id": ",".join(new_pmids), "retmode": "xml", "email": email},
                timeout=30,
            )
            root = ET.fromstring(xml_data)

            for article in root.findall(".//PubmedArticle"):
                pmid_el = article.find(".//PMID")
                title_el = article.find(".//ArticleTitle")
                abstract_el = article.find(".//AbstractText")
                doi_el = article.find(".//ArticleId[@IdType='doi']")
                year_el = article.find(".//PubDate/Year")

                if not (title_el is not None and abstract_el is not None):
                    continue
                doi = normalize_doi(doi_el.text) if doi_el is not None and doi_el.text else ""
                results.append({
                    "source": "pubmed",
                    "pmid": pmid_el.text if pmid_el is not None else "",
                    "doi": doi,
                    "title": "".join(title_el.itertext()).strip(),
                    "abstract": "".join(abstract_el.itertext()).strip(),
                    "year": int(year_el.text) if year_el is not None else None,
                })
            time.sleep(0.4)
        except Exception as e:
            log.warning("PubMed 오류 (query=%s): %s", query, e)

    log.info("PubMed: %d편 수집", len(results))
    return results


# ── Semantic Scholar ───────────────────────────────────────────────────────────

def fetch_semantic_scholar(queries: list[str], limit: int, api_key: str) -> list[dict]:
    results: list[dict] = []
    seen_ids: set[str] = set()
    headers = {"x-api-key": api_key} if api_key else {}
    fields = "title,abstract,year,externalIds"

    for query in queries:
        for attempt in range(3):
            try:
                time.sleep(2.0)
                data = json.loads(_http_get(
                    "https://api.semanticscholar.org/graph/v1/paper/search",
                    {"query": query, "limit": limit, "fields": fields},
                    headers=headers,
                ))
                for paper in data.get("data", []):
                    pid = paper.get("paperId", "")
                    if pid in seen_ids or not paper.get("abstract"):
                        continue
                    seen_ids.add(pid)
                    ext = paper.get("externalIds") or {}
                    doi = normalize_doi(ext.get("DOI", "") or "")
                    results.append({
                        "source": "semantic_scholar",
                        "doi": doi,
                        "title": paper.get("title", "").strip(),
                        "abstract": paper.get("abstract", "").strip(),
                        "year": paper.get("year"),
                    })
                break
            except HTTPError as e:
                if e.code == 429:
                    wait = 5 * (attempt + 1)
                    log.warning("Semantic Scholar 429 — %d초 후 재시도", wait)
                    time.sleep(wait)
                else:
                    log.warning("Semantic Scholar 오류 (query=%s): %s", query, e)
                    break
            except Exception as e:
                log.warning("Semantic Scholar 오류 (query=%s): %s", query, e)
                break

    log.info("Semantic Scholar: %d편 수집", len(results))
    return results


# ── 중복 제거 ─────────────────────────────────────────────────────────────────

def deduplicate(papers: list[dict], seen_dois: set[str]) -> list[dict]:
    result: list[dict] = []
    seen_titles: set[str] = set()

    for paper in papers:
        doi = paper.get("doi", "")
        title_key = re.sub(r"\s+", " ", paper["title"].lower().strip())

        if doi:
            if doi in seen_dois:
                continue
            seen_dois.add(doi)
        else:
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

        result.append(paper)
    return result


# ── Bedrock ───────────────────────────────────────────────────────────────────

def _bedrock_invoke(prompt: str, max_tokens: int = 512) -> str:
    client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    })
    resp = client.invoke_model(modelId=BEDROCK_MODEL_ID, body=body)
    return json.loads(resp["body"].read())["content"][0]["text"].strip()


def translate_abstract(title: str, abstract: str) -> str:
    try:
        return _bedrock_invoke(_TRANSLATE_PROMPT.format(title=title, abstract=abstract[:2000]), max_tokens=1024)
    except Exception as e:
        log.warning("번역 실패, 원문 사용: %s", e)
        return abstract


def extract_metadata(title: str, abstract: str) -> dict:
    try:
        text = _bedrock_invoke(_METADATA_PROMPT.format(title=title, abstract=abstract[:1500]), max_tokens=256)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        log.warning("메타데이터 추출 실패: %s", e)
    return {"age_group": "all", "language_area": [], "metric": [], "clinical_task": ["assessment"]}


# ── 메인 핸들러 ───────────────────────────────────────────────────────────────

def handler(event: dict, context) -> dict:
    dry_run = event.get("dry_run", False)

    log.info("=== 논문 수집 시작 (dry_run=%s, limit=%d) ===", dry_run, PAPERS_LIMIT)

    secrets = _get_secrets()
    pubmed_email = secrets.get("PUBMED_EMAIL", "")
    pubmed_api_key = secrets.get("PUBMED_API_KEY", "")
    semantic_api_key = secrets.get("SEMANTIC_SCHOLAR_API_KEY", "")

    seen_dois: set[str] = set(_s3_get_json(S3_SEEN_DOIS_KEY, []))
    paper_metadata: dict = _s3_get_json(S3_PAPER_METADATA_KEY, {})
    log.info("기존 수집 DOI: %d개", len(seen_dois))

    all_papers: list[dict] = []
    all_papers += fetch_pubmed(PUBMED_QUERIES, PAPERS_LIMIT, pubmed_email, pubmed_api_key)
    all_papers += fetch_semantic_scholar(SEMANTIC_SCHOLAR_QUERIES, PAPERS_LIMIT, semantic_api_key)
    log.info("전체 수집: %d편 (중복 제거 전)", len(all_papers))

    new_papers = deduplicate(all_papers, seen_dois)
    log.info("신규 논문: %d편", len(new_papers))

    if not new_papers:
        return {"status": "ok", "new_papers": 0}

    if dry_run:
        for p in new_papers:
            log.info("[dry-run] %s  DOI=%s", p["title"][:70], p.get("doi", "N/A"))
        return {"status": "dry_run", "new_papers": len(new_papers)}

    saved = 0
    for paper in new_papers:
        if not paper.get("abstract"):
            continue

        log.info("번역 중: %s", paper["title"][:60])
        abstract_ko = translate_abstract(paper["title"], paper["abstract"])

        log.info("메타데이터 추출 중: %s", paper["title"][:60])
        extracted = extract_metadata(paper["title"], abstract_ko)

        # ── 파일명 결정 ──
        doc_id = doi_to_doc_id(paper["doi"]) if paper.get("doi") else f"doc_paper_{paper['source']}_{int(time.time())}"
        title_safe = _safe_filename(paper["title"])
        filename = f"{doc_id}__{title_safe}.txt"
        s3_key = f"{S3_DOCUMENTS_PREFIX}/{filename}"

        # ── txt 내용 생성 ──
        lines = [f"# {paper['title']}", ""]
        if paper.get("year"):
            lines.append(f"출판연도: {paper['year']}")
        if paper.get("doi"):
            lines.append(f"DOI: {paper['doi']}")
        if abstract_ko != paper["abstract"]:
            lines += ["", "## 초록 (한국어)", "", abstract_ko,
                      "", "## Abstract (원문)", "", paper["abstract"]]
        else:
            lines += ["", "## 초록", "", paper["abstract"]]

        _s3_put_text(s3_key, "\n".join(lines))
        log.info("[S3 저장] s3://%s/%s", S3_BUCKET, s3_key)

        # ── SQS 메시지 발행 ──
        chunk_metadata = {
            "document_id": doc_id,
            "chunk_id": f"{doc_id}_chunk_0",
            "title": paper["title"],
            "source_type": "research_abstract",
            "age_group": extracted.get("age_group", "all"),
            "language_area": extracted.get("language_area", []),
            "metric": extracted.get("metric", []),
            "clinical_task": extracted.get("clinical_task", ["assessment"]),
        }
        _sqs_send({"bucket": S3_BUCKET, "key": s3_key, "metadata": chunk_metadata})
        log.info("[SQS] 발행: %s", doc_id)

        # ── 메타데이터 기록 ──
        paper_metadata[doc_id] = {
            **chunk_metadata,
            "doi": paper.get("doi", ""),
            "year": paper.get("year"),
            "api_source": paper["source"],
            "collected_at": str(date.today()),
        }

        saved += 1
        time.sleep(0.5)

    _s3_put_json(S3_SEEN_DOIS_KEY, sorted(seen_dois))
    _s3_put_json(S3_PAPER_METADATA_KEY, paper_metadata)
    log.info("=== 완료: %d편 저장 ===", saved)

    return {"status": "ok", "new_papers": saved}
