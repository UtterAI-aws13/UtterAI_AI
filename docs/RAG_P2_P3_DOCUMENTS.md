# RAG P2/P3 문서 작업 기록

> 작성일: 2026-06-22  
> 작업 범위: RAG 지식베이스 5단계 — P2/P3 임상 가이드 추가

## 1. 작업 범위

기존 P1에 이미 포함된 유창성·학령기 통합 가이드는 중복 작성하지 않았다. P2 설계 8개, P3의 FCM/AAC 3개, 단계 계획에 명시된 음성장애 1개를 추가했다.

| document_id | age_group | 주요 language_area |
|---|---|---|
| `doc_asd_pragmatics` | preschool | pragmatics, aac |
| `doc_dld_vs_delay` | preschool | expressive_language, receptive_language, morphosyntax |
| `doc_milieu_teaching` | preschool | expressive_language, receptive_language, pragmatics |
| `doc_narrative_intervention` | school_age | narrative_discourse |
| `doc_adult_discourse` | adult | narrative_discourse, functional_communication |
| `doc_tbi_cognitive_comm` | adult | cognitive_communication, pragmatics |
| `doc_dementia_language` | adult | cognitive_communication, aac |
| `doc_dysarthria_types` | adult | motor_speech, functional_communication |
| `doc_fcm_guide` | adult | functional_communication, clinical_documentation |
| `doc_aac_child` | preschool | aac, pragmatics |
| `doc_aac_adult` | adult | aac, functional_communication |
| `doc_voice_disorders` | adult | voice, functional_communication |

## 2. 설계 원칙

- 단일 점수나 관찰로 진단을 확정하지 않는다.
- 손상 수준뿐 아니라 활동·참여와 환경 요인을 함께 기록한다.
- AAC는 선수 능력을 요구하지 않고 현재 의사소통 요구를 기준으로 고려한다.
- ASD 문서는 눈맞춤이나 신경전형적 행동 강요 대신 기능과 자율성을 중심으로 작성한다.
- 치매·음성장애·급성 TBI의 의료적 위험 신호는 관련 의료진 평가와 연결한다.
- 표준 척도와 검사도구의 공식 매뉴얼·저작권 기준을 우선한다.

## 3. 코드 연결

`scripts/ingest_rag_docs.py`의 `DOC_METADATA`에 12개 문서를 등록했다. 각 문서에 `age_group`, `language_area`, `metric`, `clinical_task`, `assessment_tool`을 지정했다.

`app/rag/ontology.yaml`에는 다음 검색 개념을 추가했다.

- DLD
- milieu_teaching
- TBI
- dementia
- dysarthria
- FCM
- voice_disorder

기존 `ASD`, `AAC`, `CIU`, `main_concept`, `cognitive_communication`, `motor_speech`, `functional_goal` 개념과 함께 신규 문서를 검색한다.

## 4. 검증 결과

- 신규 문서 파일과 `DOC_METADATA` 매핑: 12/12
- ontology YAML 파싱 및 대표 필터 4종: 통과
- Ruff: 통과
- Pytest: 38 passed
- `git diff --check`: 통과

## 5. 다음 작업

문서를 pgvector에 인제스트한 뒤 레이어 1 평가를 다시 실행한다.

```bash
APP_ENV=local uv run python scripts/ingest_rag_docs.py
APP_ENV=local uv run python scripts/eval_retrieval.py
```

기존 문서가 이미 인제스트된 환경에서 신규 문서만 추가하는 경우 기본 실행으로 충분하다. 신규 문서 검색 결과를 확인한 뒤 골든 QA 셋과 RAGAS 레이어 2 평가를 진행한다.

## 6. 주요 근거

- ASHA Practice Portal: Autism, Spoken Language Disorders, TBI in Adults, Dementia, Dysarthria in Adults, Aphasia, AAC, Voice Disorders
- NIDCD: Developmental Language Disorder
- WHO: International Classification of Functioning, Disability and Health

