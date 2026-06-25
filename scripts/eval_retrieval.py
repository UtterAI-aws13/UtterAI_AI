"""
RAG 검색 품질 수동 검증 스크립트 (레이어 1).

지표:
  - Recall@5    : 기대 문서가 상위 5개 안에 있는 비율  (목표 ≥ 0.80)
  - Precision@5 : 상위 5개 중 기대 문서 비율           (목표 ≥ 0.60)
  - MRR         : 기대 문서의 평균 역순위               (목표 ≥ 0.70)
  - 필터 오염률 : forbidden_age_group 청크 혼입 비율    (목표 0%)

실행: APP_ENV=local python scripts/eval_retrieval.py
결과: docs/eval/ 폴더에 날짜별 PNG 차트 저장
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

load_dotenv()

CHART_DIR = Path(__file__).parent.parent / "docs" / "eval"

EVAL_CASES = [
    {
        "query": "MLU 계산할 때 반복 발화는 어떻게 처리해야 하나요?",
        "expected_docs": ["doc_metric_exception_rule", "doc_metric_mlu_korean_rule"],
        "forbidden_age_group": ["adult"],
    },
    {
        "query": "격조사 오류가 많은 만 4세 아동 평가",
        "expected_docs": ["doc_korean_morphosyntax", "doc_language_sample_metrics"],
        "forbidden_age_group": ["adult"],
    },
    {
        "query": "성인 실어증 CIU 분석 결과 해석",
        "expected_docs": ["doc_metric_ciu_korean_rule", "doc_adult_slp_guide"],
        "forbidden_age_group": ["preschool"],
    },
    {
        "query": "리포트에 장애가 있다고 써도 되나요?",
        "expected_docs": ["doc_report_safety_rule"],
        "forbidden_age_group": [],
    },
    {
        "query": "말더듬 아동 중재 방법",
        "expected_docs": ["doc_fluency_guide"],
        "forbidden_age_group": [],
    },
    {
        "query": "초등학교 3학년 이야기 구성 어려움",
        "expected_docs": ["doc_school_age_guide"],
        "forbidden_age_group": [],
    },
    {
        "query": "PRES 수용언어 점수가 표현언어 점수보다 낮아요",
        "expected_docs": ["doc_receptive_language_guide"],
        "forbidden_age_group": ["adult"],
    },
    {
        "query": "단기 목표를 어떻게 작성해야 하나요?",
        "expected_docs": ["doc_goal_writing_guide"],
        "forbidden_age_group": [],
    },
]

TOP_K = 5


def _first_rank(retrieved_docs: list[str], expected_docs: list[str]) -> int | None:
    """expected_docs 중 처음 등장하는 순위(1-based) 반환. 없으면 None."""
    for i, doc in enumerate(retrieved_docs, 1):
        if doc in expected_docs:
            return i
    return None


async def run_eval():
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.embedding_kure import KUREEmbeddingWrapper
    from app.rag.vector_store import VectorStore
    from app.config import settings
    from app.storage.db import get_engine

    print("임베딩 모델 로딩 중...")
    embedding_model = KUREEmbeddingWrapper(model_name=settings.embedding_model_name)
    embedding_model.load()
    print("완료\n")

    results = []
    async with AsyncSession(get_engine()) as session:
        vs = VectorStore(session)

        for case in EVAL_CASES:
            query_vec = embedding_model.predict([case["query"]])[0]
            chunks = await vs.search(
                embedding=query_vec,
                filters={},
                top_k=TOP_K,
                score_threshold=0.0,
            )

            retrieved_docs = [c.document_id for c in chunks]
            retrieved_age_groups = [c.metadata.get("age_group") for c in chunks]
            scores = [c.score for c in chunks]

            # Recall@K: 기대 문서 중 몇 개가 상위 K 안에 있는가
            hits = sum(1 for doc in case["expected_docs"] if doc in retrieved_docs)
            recall = hits / len(case["expected_docs"]) if case["expected_docs"] else 1.0

            # Precision@K: 상위 K 중 기대 문서 비율
            precision = hits / TOP_K if TOP_K > 0 else 0.0

            # MRR: 기대 문서 첫 등장 순위의 역수
            rank = _first_rank(retrieved_docs, case["expected_docs"])
            rr = 1.0 / rank if rank else 0.0

            # 필터 오염: forbidden_age_group 청크가 결과에 포함됐는지
            contaminated = any(
                ag in case["forbidden_age_group"]
                for ag in retrieved_age_groups
                if ag is not None
            )

            results.append({
                "query": case["query"],
                "recall": recall,
                "precision": precision,
                "rr": rr,
                "contaminated": contaminated,
                "retrieved": retrieved_docs,
                "scores": scores,
                "expected": case["expected_docs"],
            })

    # ── 결과 출력 ──────────────────────────────────────────
    W = 42
    print(f"\n{'=' * 80}")
    print(f"{'질문':{W}} {'Recall':>7} {'Prec':>7} {'RR':>7} {'오염':>5}")
    print(f"{'-' * 80}")

    for r in results:
        flag = "❌" if r["contaminated"] else "✅"
        print(
            f"{r['query'][:W]:{W}} "
            f"{r['recall']:>7.2f} "
            f"{r['precision']:>7.2f} "
            f"{r['rr']:>7.2f} "
            f"{flag:>5}"
        )
        if r["recall"] < 1.0 or r["contaminated"]:
            print(f"  기대: {r['expected']}")
            print(f"  실제: {list(zip(r['retrieved'], [f'{s:.3f}' for s in r['scores']]))}")

    avg_recall = sum(r["recall"] for r in results) / len(results)
    avg_precision = sum(r["precision"] for r in results) / len(results)
    mrr = sum(r["rr"] for r in results) / len(results)
    contamination_count = sum(1 for r in results if r["contaminated"])

    print(f"\n{'=' * 80}")
    print(f"평균 Recall@{TOP_K}  : {avg_recall:.3f}  (목표 ≥ 0.80)  {'✅' if avg_recall >= 0.80 else '❌'}")
    print(f"평균 Precision@{TOP_K}: {avg_precision:.3f}  (목표 ≥ 0.60)  {'✅' if avg_precision >= 0.60 else '❌'}")
    print(f"MRR              : {mrr:.3f}  (목표 ≥ 0.70)  {'✅' if mrr >= 0.70 else '❌'}")
    print(f"필터 오염 케이스 : {contamination_count}/{len(results)}  (목표 0개)    {'✅' if contamination_count == 0 else '❌'}")
    print(f"{'=' * 80}\n")

    chart_path = _save_charts(results, avg_recall, avg_precision, mrr, contamination_count)
    _update_eval_log(results, avg_recall, avg_precision, mrr, contamination_count, chart_path)


def _save_charts(results: list, avg_recall: float, avg_precision: float, mrr: float, contamination_count: int) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["axes.unicode_minus"] = False

    CHART_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = CHART_DIR / f"eval_layer1_{timestamp}.png"

    THRESHOLDS = {"Recall@5": 0.80, "Precision@5": 0.60, "MRR": 0.70}
    summary_values = [avg_recall, avg_precision, mrr]
    summary_labels = list(THRESHOLDS.keys())
    threshold_values = list(THRESHOLDS.values())

    case_labels = [f"Q{i+1}" for i in range(len(results))]

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.suptitle(f"RAG Layer 1 Evaluation  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}", fontsize=14, fontweight="bold")

    # ── Chart 1: Summary metrics ───────────────────────────────────
    ax = axes[0]
    colors = ["#4caf50" if v >= t else "#f44336" for v, t in zip(summary_values, threshold_values)]
    bars = ax.bar(summary_labels, summary_values, color=colors, width=0.5, zorder=3)
    for bar, t in zip(bars, threshold_values):
        ax.axhline(y=t, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    for bar, val in zip(bars, summary_values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                f"{val:.3f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.set_ylim(0, 1.15)
    ax.set_title("Summary Metrics", fontsize=12)
    ax.set_ylabel("Score")
    ax.grid(axis="y", alpha=0.3, zorder=0)
    ax.text(0.98, 0.02, "dashed = threshold", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=8, color="gray")

    # ── Chart 2: Per-case Recall ───────────────────────────────────
    ax = axes[1]
    recalls = [r["recall"] for r in results]
    colors2 = ["#4caf50" if v >= 1.0 else "#ff9800" if v > 0 else "#f44336" for v in recalls]
    bars2 = ax.barh(range(len(results)), recalls, color=colors2, zorder=3)
    ax.axvline(x=0.80, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.set_yticks(range(len(results)))
    ax.set_yticklabels(case_labels, fontsize=10)
    ax.set_xlim(0, 1.15)
    ax.set_title("Recall@5 per Case", fontsize=12)
    ax.set_xlabel("Recall")
    ax.grid(axis="x", alpha=0.3, zorder=0)
    for bar, val in zip(bars2, recalls):
        ax.text(val + 0.02, bar.get_y() + bar.get_height() / 2,
                f"{val:.2f}", va="center", fontsize=9)

    # ── Chart 3: Per-case MRR ──────────────────────────────────────
    ax = axes[2]
    mrrs = [r["rr"] for r in results]
    contaminated = [r["contaminated"] for r in results]
    colors3 = []
    for rr_val, cont in zip(mrrs, contaminated):
        if cont:
            colors3.append("#9c27b0")
        elif rr_val >= 0.70:
            colors3.append("#4caf50")
        elif rr_val > 0:
            colors3.append("#ff9800")
        else:
            colors3.append("#f44336")
    bars3 = ax.barh(range(len(results)), mrrs, color=colors3, zorder=3)
    ax.axvline(x=0.70, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.set_yticks(range(len(results)))
    ax.set_yticklabels(case_labels, fontsize=10)
    ax.set_xlim(0, 1.15)
    ax.set_title(f"MRR per Case  |  Filter Contamination: {contamination_count}", fontsize=12)
    ax.set_xlabel("MRR (Reciprocal Rank)")
    ax.grid(axis="x", alpha=0.3, zorder=0)
    for bar, val in zip(bars3, mrrs):
        ax.text(val + 0.02, bar.get_y() + bar.get_height() / 2,
                f"{val:.2f}", va="center", fontsize=9)


    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"차트 저장: {out_path}")
    return out_path


def _update_eval_log(
    results: list,
    avg_recall: float,
    avg_precision: float,
    mrr: float,
    contamination_count: int,
    chart_path: Path,
) -> None:
    log_path = CHART_DIR / "EVAL_LOG.md"
    run_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    chart_filename = chart_path.name

    # 케이스별 변화 요약 (빨강/주황만 표시)
    problem_lines = []
    for r in results:
        if r["recall"] < 1.0 or r["contaminated"]:
            flag = "🔴" if r["recall"] == 0.0 else "🟠"
            problem_lines.append(
                f"  - {flag} {r['query'][:40]} — Recall {r['recall']:.2f}, MRR {r['rr']:.2f}"
            )
    problems_block = "\n".join(problem_lines) if problem_lines else "  - 없음 (전 케이스 정상)"

    new_entry = f"""---

## 평가 — {run_time}

![차트]({chart_filename})

| 지표 | 결과 | 목표 | 판정 |
|---|---|---|---|
| Recall@5 | **{avg_recall:.3f}** | ≥ 0.80 | {'✅' if avg_recall >= 0.80 else '❌'} |
| Precision@5 | {avg_precision:.3f} | ≥ 0.60 | {'✅' if avg_precision >= 0.60 else '❌'} |
| MRR | **{mrr:.3f}** | ≥ 0.70 | {'✅' if mrr >= 0.70 else '❌'} |
| 필터 오염 | {contamination_count}/8 | 0% | {'✅' if contamination_count == 0 else '❌'} |

**주의 케이스**
{problems_block}

"""

    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        # 헤더 블록(첫 번째 --- 앞) 보존, 그 뒤에 새 항목 삽입
        if "\n---\n" in existing:
            header, rest = existing.split("\n---\n", 1)
            updated = header + "\n" + new_entry + "---\n" + rest
        else:
            updated = existing + "\n" + new_entry
    else:
        updated = new_entry

    log_path.write_text(updated, encoding="utf-8")
    print(f"평가 로그 업데이트: {log_path}")


if __name__ == "__main__":
    asyncio.run(run_eval())