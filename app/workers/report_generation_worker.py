# 5-Agent 리포트 생성 SQS Worker.
# report-generation-queue를 폴링해 Strands Graph를 실행한다.
# cpu_worker.py의 report loop와 동일한 heartbeat/에러 처리 패턴을 따른다.
# 참고: 01_production_5_agent_agentic_rag_design.md §20
import asyncio
import threading

import boto3
from loguru import logger
from opentelemetry import trace

from app.agents.report_generation.errors import DuplicateRunError, ReportGenerationError
from app.agents.report_generation.graph import build_default_dependencies, run_report_generation
from app.config import settings
from app.observability.otel import initialize_observability
from app.observability.phoenix import OI_CHAIN, safe_id, set_openinference_span_kind, set_safe_attributes
from app.schemas.report_generation import ReportGenerationQueueMessage


def _extend_visibility(
    sqs, queue_url: str, receipt_handle: str, stop_event: threading.Event, interval: int = 240
) -> None:
    """리포트 생성은 근거 재검색/재작성 cycle 때문에 수 분~수십 분 걸릴 수 있어
    주기적으로 VisibilityTimeout을 연장한다 (cpu_worker.py와 동일한 패턴)."""
    while True:
        try:
            sqs.change_message_visibility(
                QueueUrl=queue_url, ReceiptHandle=receipt_handle, VisibilityTimeout=1800
            )
        except Exception as e:
            logger.warning(f"[report-generation-heartbeat] VisibilityTimeout 연장 실패: {e}")
        if stop_event.wait(interval):
            break


def _make_sqs_client():
    return boto3.client("sqs", region_name=settings.aws_region)


def run_loop() -> None:
    logger.info(f"Report Generation Worker 시작. 큐: {settings.sqs_report_generation_queue_url}")
    sqs = _make_sqs_client()

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=settings.sqs_report_generation_queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                VisibilityTimeout=1800,
            )
        except Exception as e:
            logger.error(f"[report-generation-loop] SQS receive_message 실패: {e}")
            sqs = _make_sqs_client()
            continue

        messages = response.get("Messages", [])
        if not messages:
            continue

        raw = messages[0]
        receipt_handle = raw["ReceiptHandle"]

        try:
            msg = ReportGenerationQueueMessage.model_validate_json(raw["Body"])
        except Exception as e:
            logger.exception(f"[report-generation-loop] 메시지 파싱 실패: {e}")
            # 파싱 자체가 불가능한 메시지는 재시도해도 의미가 없다 - 즉시 삭제한다.
            sqs.delete_message(
                QueueUrl=settings.sqs_report_generation_queue_url, ReceiptHandle=receipt_handle
            )
            continue

        stop_event = threading.Event()
        heartbeat = threading.Thread(
            target=_extend_visibility,
            args=(sqs, settings.sqs_report_generation_queue_url, receipt_handle, stop_event),
            daemon=True,
        )
        heartbeat.start()

        try:
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span(
                "worker.report_generation.message", kind=trace.SpanKind.CONSUMER
            ) as span:
                set_openinference_span_kind(span, OI_CHAIN)
                set_safe_attributes(span, {
                    "run.hash": safe_id(msg.run_id),
                    "session.hash": safe_id(msg.session_id),
                    "worker.queue": "report-generation",
                })

                logger.info(f"[report-generation-loop] 메시지 수신 run_id={msg.run_id}")
                deps = build_default_dependencies()
                try:
                    final_state = asyncio.run(
                        run_report_generation(
                            session_id=msg.session_id,
                            patient_ref_id=msg.patient_ref_id,
                            therapist_id=msg.therapist_id,
                            selected_analysis=msg.selected_analysis,
                            history_session_count=msg.history_session_count,
                            deps=deps,
                            run_id=msg.run_id,
                        )
                    )
                    logger.info(
                        f"[report-generation-loop] run_id={msg.run_id} 종료 status={final_state.status}"
                    )
                except DuplicateRunError as e:
                    # 이미 처리 중인 run - non-retryable, 메시지만 소진한다 (§26.2).
                    logger.warning(f"[report-generation-loop] 중복 run_id={msg.run_id}: {e}")
                except ReportGenerationError as e:
                    # Graph 내부에서 이미 FAILED로 저장했다 - SQS 레벨 재시도는 불필요하다.
                    logger.warning(f"[report-generation-loop] run_id={msg.run_id} graph 오류: {e}")

                # Graph가 SAVED/HUMAN_REVIEW/FAILED 중 어떤 상태로 끝나든, Graph 자체
                # 실행은 정상 완료된 것이므로 메시지를 삭제한다. SQS 레벨 재시도는
                # 아래 except(예상 못한 예외/크래시)에서만 발생한다.
                sqs.delete_message(
                    QueueUrl=settings.sqs_report_generation_queue_url, ReceiptHandle=receipt_handle
                )
        except Exception as e:
            logger.exception(f"[report-generation-loop] 처리 중 예외 발생 run_id={msg.run_id}: {e}")
            try:
                sqs.change_message_visibility(
                    QueueUrl=settings.sqs_report_generation_queue_url,
                    ReceiptHandle=receipt_handle,
                    VisibilityTimeout=0,
                )
            except Exception as vis_e:
                logger.warning(f"[report-generation-loop] VisibilityTimeout 즉시 해제 실패: {vis_e}")
        finally:
            stop_event.set()


def start_worker() -> None:
    """독립 실행용 진입점. cpu_worker.py처럼 이미 다른 워커와 같은 프로세스에서
    같이 도는 경우에는 initialize_observability() 중복 호출을 피하기 위해
    run_loop()을 직접 스레드로 돌린다."""
    initialize_observability()
    run_loop()


if __name__ == "__main__":
    start_worker()
