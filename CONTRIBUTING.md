# Contributing

## Branch Rules

- 기본 개발 브랜치는 `dev`다.
- 새 작업은 `dev`에서 분기한다.
- 브랜치 네이밍 규칙:
  - `feature/<issue-number>-<short-name>`
  - `fix/<issue-number>-<short-name>`
  - `docs/<issue-number>-<short-name>`
  - `chore/<issue-number>-<short-name>`

예시:

- `feature/12-bedrock-integration`
- `fix/21-sqs-queue-url-key`
- `docs/03-codeflow-update`

## Commit Rules

- 커밋 메시지는 짧고 목적이 분명해야 한다.
- 권장 prefix:
  - `feat:`
  - `fix:`
  - `docs:`
  - `refactor:`
  - `test:`
  - `chore:`

예시:

- `feat: add bedrock claude report pipeline`
- `fix: correct sqs queue url config key in jobs.py`
- `chore: migrate from pip to uv`

## Issue Rules

- 작업 시작 전 이슈를 먼저 만든다.
- 하나의 이슈는 하나의 목적에 집중한다.
- 이슈에는 배경, 목표, 완료 조건을 반드시 적는다.
- AI 파이프라인 관련 이슈는 영향받는 Worker(CPU/ML GPU/LLM GPU)와 SQS 큐를 명시한다.

## Pull Request Rules

- PR base는 기본적으로 `dev`다.
- PR 하나에는 하나의 논리적 변경만 담는다.
- 초안 상태에서는 `Draft PR`을 사용한다.
- PR 본문에는 변경 내용, 테스트 결과, 영향 범위, 리뷰 포인트를 적는다.
- 모델 변경이나 파이프라인 변경은 로컬 테스트 결과(스크립트 출력 또는 로그)를 포함한다.
- 머지 전 최소 1회 이상 셀프 리뷰를 수행한다.

## Review Checklist

- 요구사항과 실제 변경 범위가 일치하는가
- SQS 메시지 스키마 변경 시 발신/수신 Worker 양쪽에 반영했는가
- 환경 변수 추가 시 `.env.example`도 함께 업데이트했는가
- S3 키 구조 변경 시 업로드/다운로드 양쪽에 반영했는가
- 로그에 음성 원문, 전사 텍스트, 개인정보가 노출되지 않는가
- 테스트 스크립트로 로컬 검증 결과가 있는가

## 로컬 개발 환경

자세한 설치 및 실행 절차는 `README.md`의 **로컬 실행** 섹션 참고.

현재 코드 흐름과 알려진 버그 목록은 `docs/CODEFLOW_DETAILED.md` 참고.
