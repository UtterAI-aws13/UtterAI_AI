"""
논문 수집 배치 스크립트.

3개 API에서 한국어 언어재활 관련 논문 메타데이터를 수집한다.
월 1회 배치로 실행하며, DOI 기준으로 중복을 제거한다.

흐름:
  1. 각 API에서 논문 메타데이터(제목·초록·DOI) 수집
  2. DOI 기준 중복 제거 (.seen_dois.json)
  3. Bedrock Claude로 abstract → age_group/language_area/metric 추출
  4. 초록을 .txt로 저장 (docs/papers/)
  5. paper_metadata.json 업데이트 → ingest_rag_docs.py가 읽어 인제스트

사용법:
  python scripts/collect_papers.py
  python scripts/collect_papers.py --dry-run        # 저장 없이 수집 대상만 출력
  python scripts/collect_papers.py --limit 30       # API당 최대 30편
  python scripts/collect_papers.py --skip-bedrock   # 메타데이터 추출 건너뜀

필요 환경 변수 (.env):
  PUBMED_EMAIL              PubMed polite access용 이메일 (필수)
  PUBMED_API_KEY            PubMed API key (선택)
  SEMANTIC_SCHOLAR_API_KEY  Semantic Scholar API key (선택, 없으면 1 req/s)
  AWS_REGION / BEDROCK_REGION  Bedrock 리전
"""
import argparse
import json
import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
PAPERS_DIR = ROOT / "docs" / "papers"
SEEN_DOIS_FILE = PAPERS_DIR / ".seen_dois.json"
PAPER_METADATA_FILE = PAPERS_DIR / "paper_metadata.json"

PAPERS_DIR.mkdir(parents=True, exist_ok=True)

# ── 검색 쿼리 ──────────────────────────────────────────────────────────────────

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


# ── DOI 중복 관리 ──────────────────────────────────────────────────────────────

def load_seen_dois() -> set[str]:
    if SEEN_DOIS_FILE.exists():
        return set(json.loads(SEEN_DOIS_FILE.read_text()))
    return set()


def save_seen_dois(dois: set[str]) -> None:
    SEEN_DOIS_FILE.write_text(json.dumps(sorted(dois), ensure_ascii=False, indent=2))


def normalize_doi(doi: str) -> str:
    return doi.lower().strip().removeprefix("https://doi.org/").removeprefix("http://doi.org/")


def doi_to_doc_id(doi: str) -> str:
    safe = re.sub(r"[^a-z0-9]", "_", normalize_doi(doi))
    return f"doc_paper_{safe}"


# ── PubMed ────────────────────────────────────────────────────────────────────

def fetch_pubmed(queries: list[str], limit: int) -> list[dict]:
    try:
        import requests
    except ImportError:
        log.warning("requests 미설치 — PubMed 건너뜀 (pip install requests)")
        return []

    email = os.environ.get("PUBMED_EMAIL", "")
    api_key = os.environ.get("PUBMED_API_KEY", "")
    if not email:
        log.warning("PUBMED_EMAIL 미설정 — PubMed 건너뜀")
        return []

    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    results: list[dict] = []
    seen_pmids: set[str] = set()

    for query in queries:
        try:
            params = {
                "db": "pubmed", "term": query, "retmode": "json",
                "retmax": limit, "email": email,
            }
            if api_key:
                params["api_key"] = api_key

            r = requests.get(f"{base}/esearch.fcgi", params=params, timeout=15)
            r.raise_for_status()
            pmids = r.json().get("esearchresult", {}).get("idlist", [])
            new_pmids = [p for p in pmids if p not in seen_pmids]
            seen_pmids.update(new_pmids)
            if not new_pmids:
                continue

            time.sleep(0.4)
            r2 = requests.get(
                f"{base}/efetch.fcgi",
                params={"db": "pubmed", "id": ",".join(new_pmids), "retmode": "xml", "email": email},
                timeout=30,
            )
            r2.raise_for_status()
            root = ET.fromstring(r2.content)

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

def fetch_semantic_scholar(queries: list[str], limit: int) -> list[dict]:
    try:
        import requests
    except ImportError:
        log.warning("requests 미설치 — Semantic Scholar 건너뜀")
        return []

    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    headers = {"x-api-key": api_key} if api_key else {}
    results: list[dict] = []
    seen_ids: set[str] = set()

    fields = "title,abstract,year,externalIds"
    for query in queries:
        for attempt in range(3):
            try:
                time.sleep(2.0)
                r = requests.get(
                    "https://api.semanticscholar.org/graph/v1/paper/search",
                    params={"query": query, "limit": limit, "fields": fields},
                    headers=headers,
                    timeout=20,
                )
                if r.status_code == 429:
                    wait = 5 * (attempt + 1)
                    log.warning("Semantic Scholar 429 — %d초 후 재시도 (attempt %d/3)", wait, attempt + 1)
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                for paper in r.json().get("data", []):
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
            except Exception as e:
                log.warning("Semantic Scholar 오류 (query=%s): %s", query, e)
                break

    log.info("Semantic Scholar: %d편 수집", len(results))
    return results


# ── CrossRef DOI 보강 ─────────────────────────────────────────────────────────

def enrich_doi_via_crossref(papers: list[dict]) -> list[dict]:
    """DOI가 없는 논문에 CrossRef로 DOI를 보강한다."""
    try:
        import requests
    except ImportError:
        return papers

    enriched = []
    for paper in papers:
        if paper.get("doi"):
            enriched.append(paper)
            continue
        try:
            r = requests.get(
                "https://api.crossref.org/works",
                params={
                    "query.title": paper["title"],
                    "rows": 1,
                    "select": "DOI,title,published",
                },
                headers={"User-Agent": "UtterAI/1.0 (mailto:eunbin584836@gmail.com)"},
                timeout=10,
            )
            items = r.json().get("message", {}).get("items", [])
            if items:
                doi = normalize_doi(items[0].get("DOI", ""))
                paper = {**paper, "doi": doi}
            time.sleep(0.1)
        except Exception:
            pass
        enriched.append(paper)
    return enriched


# ── Bedrock 메타데이터 추출 ────────────────────────────────────────────────────

_METADATA_PROMPT = """\
다음 언어재활 관련 논문의 제목과 초록을 읽고, JSON 형식으로 메타데이터를 추출하세요.

제목: {title}

초록: {abstract}

아래 필드를 추출하고 JSON만 출력하세요. 불확실하면 가장 가능성 높은 값을 선택하세요.

age_group (하나만 선택):
  "preschool"   — 취학 전 아동 (0~6세)
  "school_age"  — 학령기 아동 (7~12세)
  "adult"       — 성인
  "all"         — 전 연령 또는 명시 없음

language_area (해당하는 것 모두, 배열):
  expressive_language, receptive_language, phonology, morphosyntax,
  vocabulary, pragmatics, fluency, narrative_discourse, motor_speech,
  cognitive_communication, functional_communication, clinical_documentation

metric (해당하는 것 모두, 배열, 없으면 빈 배열):
  mlu_morpheme, mlu_word, ndw, ntw, ttr, pcc, ciu_count, ciu_ratio,
  percent_ss, llu_morpheme

clinical_task (해당하는 것 모두, 배열):
  assessment, intervention, report_generation, goal_writing

출력 예시:
{{"age_group": "preschool", "language_area": ["expressive_language", "morphosyntax"], "metric": ["mlu_morpheme"], "clinical_task": ["assessment"]}}
"""

_TRANSLATE_PROMPT = """\
다음 언어재활 논문의 제목과 영어 초록을 한국어로 번역하세요.
전문 임상 용어(MLU, PCC, CIU, DLD 등 약어)는 그대로 유지하세요.
번역문만 출력하고 다른 설명은 쓰지 마세요.

제목: {title}

영어 초록:
{abstract}
"""


def translate_abstract_with_bedrock(title: str, abstract: str, model_id: str, region: str) -> str:
    try:
        import boto3

        client = boto3.client("bedrock-runtime", region_name=region)
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "messages": [{
                "role": "user",
                "content": _TRANSLATE_PROMPT.format(title=title, abstract=abstract[:2000]),
            }],
        })
        resp = client.invoke_model(modelId=model_id, body=body)
        return json.loads(resp["body"].read())["content"][0]["text"].strip()
    except Exception as e:
        log.warning("Bedrock 번역 실패, 원문 사용: %s", e)
        return abstract


def extract_metadata_with_bedrock(title: str, abstract: str, model_id: str, region: str) -> dict:
    try:
        import boto3

        client = boto3.client("bedrock-runtime", region_name=region)
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 256,
            "messages": [{
                "role": "user",
                "content": _METADATA_PROMPT.format(title=title, abstract=abstract[:1500]),
            }],
        })
        resp = client.invoke_model(modelId=model_id, body=body)
        text = json.loads(resp["body"].read())["content"][0]["text"].strip()

        # JSON 블록만 추출
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        log.warning("Bedrock 메타데이터 추출 실패: %s", e)

    return {
        "age_group": "all",
        "language_area": [],
        "metric": [],
        "clinical_task": ["assessment"],
    }


# ── 논문 저장 ─────────────────────────────────────────────────────────────────

def _safe_filename(text: str, max_len: int = 40) -> str:
    text = re.sub(r"[^\w\s가-힣]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:max_len]


def save_paper_as_txt(paper: dict, metadata: dict, abstract_ko: str = "") -> Path:
    doc_id = doi_to_doc_id(paper["doi"]) if paper.get("doi") else f"doc_paper_{paper['source']}_{int(time.time())}"
    title_safe = _safe_filename(paper["title"])
    filename = f"{doc_id}__{title_safe}.txt"
    filepath = PAPERS_DIR / filename

    content_lines = [
        f"# {paper['title']}",
        "",
    ]
    if paper.get("year"):
        content_lines.append(f"출판연도: {paper['year']}")
    if paper.get("doi"):
        content_lines.append(f"DOI: {paper['doi']}")

    if abstract_ko and abstract_ko != paper["abstract"]:
        content_lines += ["", "## 초록 (한국어)", "", abstract_ko,
                          "", "## Abstract (원문)", "", paper["abstract"]]
    else:
        content_lines += ["", "## 초록", "", paper["abstract"]]

    filepath.write_text("\n".join(content_lines), encoding="utf-8")
    return filepath


# ── paper_metadata.json 관리 ──────────────────────────────────────────────────

def load_paper_metadata() -> dict:
    if PAPER_METADATA_FILE.exists():
        return json.loads(PAPER_METADATA_FILE.read_text())
    return {}


def save_paper_metadata(metadata: dict) -> None:
    PAPER_METADATA_FILE.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2)
    )


# ── 중복 제거 ─────────────────────────────────────────────────────────────────

def deduplicate(papers: list[dict], seen_dois: set[str]) -> list[dict]:
    """
    1. DOI 있는 논문: DOI 기준 중복 제거
    2. DOI 없는 논문: 제목 기준 중복 제거
    """
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


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="논문 수집 배치 스크립트")
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 수집 대상만 출력")
    parser.add_argument("--limit", type=int, default=20, help="API당 쿼리당 최대 수집 편수 (기본 20)")
    parser.add_argument("--skip-bedrock", action="store_true", help="Bedrock 메타데이터 추출 건너뜀")
    args = parser.parse_args()

    bedrock_region = os.environ.get("BEDROCK_REGION") or os.environ.get("AWS_REGION", "ap-northeast-2")
    bedrock_model = os.environ.get("BEDROCK_PAPER_MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0")

    seen_dois = load_seen_dois()
    paper_metadata = load_paper_metadata()

    log.info("=== 논문 수집 시작 (limit=%d, dry_run=%s) ===", args.limit, args.dry_run)
    log.info("기존 수집 DOI: %d개", len(seen_dois))

    # ── 1. 수집 ──
    all_papers: list[dict] = []
    all_papers += fetch_pubmed(PUBMED_QUERIES, args.limit)
    all_papers += fetch_semantic_scholar(SEMANTIC_SCHOLAR_QUERIES, args.limit)

    log.info("전체 수집: %d편 (중복 제거 전)", len(all_papers))

    # ── 2. CrossRef DOI 보강 ──
    all_papers = enrich_doi_via_crossref(all_papers)

    # ── 3. 중복 제거 ──
    new_papers = deduplicate(all_papers, seen_dois)
    log.info("신규 논문: %d편", len(new_papers))

    if not new_papers:
        log.info("새로 수집할 논문이 없습니다.")
        return

    if args.dry_run:
        for p in new_papers:
            print(f"[{p['source']}] {p['title'][:70]}  DOI={p.get('doi', 'N/A')}")
        print(f"\n총 {len(new_papers)}편 (dry-run, 저장 안 함)")
        return

    # ── 4. Bedrock 메타데이터 추출 + 저장 ──
    saved = 0
    for paper in new_papers:
        if not paper.get("abstract"):
            log.debug("초록 없음, 건너뜀: %s", paper["title"][:60])
            continue

        # Bedrock으로 번역 + 메타데이터 추출
        if args.skip_bedrock:
            abstract_ko = paper["abstract"]
            extracted = {"age_group": "all", "language_area": [], "metric": [], "clinical_task": ["assessment"]}
        else:
            log.info("번역 중: %s", paper["title"][:60])
            abstract_ko = translate_abstract_with_bedrock(
                paper["title"], paper["abstract"], bedrock_model, bedrock_region
            )
            log.info("메타데이터 추출 중: %s", paper["title"][:60])
            extracted = extract_metadata_with_bedrock(
                paper["title"], abstract_ko, bedrock_model, bedrock_region
            )

        # txt 파일 저장 (한국어 번역 초록 포함)
        filepath = save_paper_as_txt(paper, extracted, abstract_ko=abstract_ko)

        # doc_id 확정
        doc_id = filepath.stem.split("__")[0]

        # paper_metadata.json 항목 추가
        paper_metadata[doc_id] = {
            "document_id": doc_id,
            "title": paper["title"],
            "source_type": "research_abstract",
            "age_group": extracted.get("age_group", "all"),
            "language_area": extracted.get("language_area", []),
            "metric": extracted.get("metric", []),
            "clinical_task": extracted.get("clinical_task", ["assessment"]),
            "assessment_tool": [],
            "doi": paper.get("doi", ""),
            "year": paper.get("year"),
            "api_source": paper["source"],
            "collected_at": str(date.today()),
        }

        log.info("[저장] %s → %s", paper["title"][:50], filepath.name)
        saved += 1

        # API 부하 분산
        if not args.skip_bedrock:
            time.sleep(0.5)

    # ── 5. 상태 저장 ──
    save_seen_dois(seen_dois)
    save_paper_metadata(paper_metadata)

    log.info("=== 완료: %d편 저장, paper_metadata.json 업데이트 ===", saved)
    log.info("다음 단계: python scripts/ingest_rag_docs.py")


if __name__ == "__main__":
    main()
