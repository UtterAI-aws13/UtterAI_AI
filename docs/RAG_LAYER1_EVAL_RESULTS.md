# RAG 레이어 1 평가 결과

> 최초 실행일: 2026-06-20 / 최종 업데이트: 2026-06-20  
> 대상: UtterAI RAG 파이프라인 (pgvector + KURE-v1)  
> 평가 스크립트: `scripts/eval_retrieval.py`

---

## 1. 평가 개요

RAG_EVALUATION_GUIDE.md 레이어 1 기준에 따라 검색 품질을 측정했다.  
평가 케이스 8개, 지표 4종 (Recall@5, Precision@5, MRR, 필터 오염률).

---

## 2. 최종 결과

### 2차 평가 (2026-06-20, `doc_korean_morphosyntax` 보강 후)

| 지표 | 결과 | 목표 | 판정 |
|---|---|---|---|
| Recall@5 | **0.938** | ≥ 0.80 | ✅ |
| Precision@5 | 0.250 | ≥ 0.60 | ❌ |
| MRR | **1.000** | ≥ 0.70 | ✅ |
| 필터 오염률 | 0/8 | 0% | ✅ |

| 질문 | Recall | MRR | 필터오염 |
|---|---|---|---|
| MLU 계산 시 반복 발화 처리 | 1.00 | 1.00 | ✅ |
| 격조사 오류가 많은 만 4세 아동 평가 | 0.50 | 1.00 | ✅ |
| 성인 실어증 CIU 분석 결과 해석 | 1.00 | 1.00 | ✅ |
| 리포트에 장애가 있다고 써도 되나요? | 1.00 | 1.00 | ✅ |
| 말더듬 아동 중재 방법 | 1.00 | 1.00 | ✅ |
| 초등학교 3학년 이야기 구성 어려움 | 1.00 | 1.00 | ✅ |
| PRES 수용언어 점수 해석 | 1.00 | 1.00 | ✅ |
| 단기 목표 작성 방법 | 1.00 | 1.00 | ✅ |

> 격조사 케이스: `doc_korean_morphosyntax` score 0.724로 1위 진입. `doc_language_sample_metrics`는 여전히 상위 5개 밖.

### 1차 평가 (2026-06-20, IVFFlat 인덱스 삭제 직후)

| 지표 | 결과 | 목표 | 판정 |
|---|---|---|---|
| Recall@5 | 0.875 | ≥ 0.80 | ✅ |
| Precision@5 | 0.225 | ≥ 0.60 | ❌ |
| MRR | 0.875 | ≥ 0.70 | ✅ |
| 필터 오염률 | 0/8 | 0% | ✅ |

| 질문 | Recall | MRR | 필터오염 |
|---|---|---|---|
| MLU 계산 시 반복 발화 처리 | 1.00 | 1.00 | ✅ |
| 격조사 오류가 많은 만 4세 아동 평가 | **0.00** | 0.00 | ✅ |
| 성인 실어증 CIU 분석 결과 해석 | 1.00 | 1.00 | ✅ |
| 리포트에 장애가 있다고 써도 되나요? | 1.00 | 1.00 | ✅ |
| 말더듬 아동 중재 방법 | 1.00 | 1.00 | ✅ |
| 초등학교 3학년 이야기 구성 어려움 | 1.00 | 1.00 | ✅ |
| PRES 수용언어 점수 해석 | 1.00 | 1.00 | ✅ |
| 단기 목표 작성 방법 | 1.00 | 1.00 | ✅ |

---

## 3. 발견된 문제 및 조치

### 3-1. IVFFlat 인덱스 과분할 (치명적 버그)

**증상**  
- "격조사" 쿼리: 결과 0개 반환 (문서는 DB에 존재함)  
- "단기목표" 쿼리: `doc_goal_writing_guide`(score 0.71)가 있음에도 관련 없는 문서만 반환  

**원인**  
`init_db.sql`에 IVFFlat 인덱스가 `lists=100`으로 생성되어 있었다.

```sql
CREATE INDEX idx_rag_chunks_embedding
    ON rag_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

IVFFlat은 벡터 공간을 `lists`개 클러스터로 나눈 뒤 검색 시 `probes`개 클러스터만 탐색한다 (기본 `probes=1`). 495개 청크에 `lists=100`이면 클러스터당 평균 5개 청크이고, 검색 범위가 전체의 1%에 불과하다.

```
탐색 범위 = probes / lists = 1 / 100 = 1%
pgvector 권장: lists = sqrt(row수) ≈ sqrt(495) ≈ 22
```

**조치**  
개발 단계(< 1000청크) 동안 인덱스를 삭제하고 sequential scan으로 전환했다.

```sql
DROP INDEX IF EXISTS idx_rag_chunks_embedding;
```

**인덱스 재생성 기준**  
청크 수가 충분히 늘어나면 아래 기준으로 재생성한다.

| 청크 수 | 권장 lists | 비고 |
|---|---|---|
| < 1,000 | 인덱스 불필요 | sequential scan이 더 정확 |
| 1,000 ~ 10,000 | ~32 | sqrt(n) 기준 |
| 10,000 ~ 100,000 | ~100 | |
| 100,000+ | ~316 | HNSW 전환 검토 |

### 3-2. 격조사 쿼리 Recall 부분 개선 (진행 중)

**1차 평가 증상**  
"격조사 오류가 많은 만 4세 아동 평가" 쿼리에서 기대 문서(`doc_korean_morphosyntax`, `doc_language_sample_metrics`) 미검색. Recall 0.00.

**원인 분류**: 어휘 미스매치 (쿼리의 "격조사 오류", "만 4세 평가" 표현이 문서 내용과 임베딩 유사도가 낮았음)

**2차 평가 결과 (문서 보강 후)**  
`doc_korean_morphosyntax` 내용 보강 (10청크 → 13청크) 후 재인제스트.

```
doc_korean_morphosyntax  0.724  ← 1위 진입
doc_korean_morphosyntax  0.718
doc_korean_morphosyntax  0.694
doc_korean_morphosyntax  0.659
doc_language_sample_analysis  0.593
```

`doc_korean_morphosyntax` 검색 성공 → Recall 0.00 → **0.50**, MRR 0.00 → **1.00**  
`doc_language_sample_metrics`는 여전히 상위 5개 밖 → Recall 1.00 미달.

**잔여 개선 방향**  
- `doc_language_sample_metrics` 내용에 격조사/형태통사 관련 표현 보강

---

## 4. Precision@5가 낮은 이유

현재 Precision@5 = 0.225. 목표 0.60 대비 낮다.

상위 5개 결과 중 기대 문서가 1~2개이고 나머지는 관련 있지만 직접적이지 않은 문서다 (e.g., `doc_language_sample_analysis`가 여러 쿼리에서 반복 등장). 이는 현재 P1까지만 문서가 갖춰진 상태에서 `doc_language_sample_analysis`(217개 청크)가 검색을 과점하는 현상이다.

P2/P3 문서가 추가되면 전반적인 유사도 분포가 고르게 되어 자연히 개선될 것으로 예상한다.

---

## 5. 다음 단계

| 작업 | 조건 | 비고 |
|---|---|---|
| 격조사 쿼리 개선 | `doc_language_sample_metrics` 내용 보강 | doc_korean_morphosyntax는 2차에서 해결 |
| Precision@5 개선 확인 | P2/P3 문서 추가 후 재실행 | 자연 개선 기대 |
| IVFFlat 인덱스 재생성 | 청크 1,000개 이상 시 | `lists = round(sqrt(n))` |
| 레이어 2 (RAGAS) 실행 | P2/P3 문서 + 골든 QA 셋 준비 후 | RAG_EVALUATION_GUIDE.md 참고 |