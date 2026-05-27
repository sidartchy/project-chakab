import asyncio

from celery import Task
from celery.utils.log import get_task_logger

from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)

# Retry budget for the self-healing loop (Phase 4)
MAX_SANDBOX_RETRIES = 3


class AgentTask(Task):
    """Base task class with shared error handling."""

    abstract = True

    def on_failure(
        self, exc: Exception, task_id: str, args: tuple, kwargs: dict, einfo
    ) -> None:  # type: ignore[override]
        logger.error(
            "task_failed",
            task_id=task_id,
            exc=str(exc),
            kwargs=kwargs,
        )


@celery_app.task(
    bind=True,
    base=AgentTask,
    name="agent.process_issue",
    max_retries=0,          # we manage retries ourselves inside the task
    default_retry_delay=30,
)
def process_issue(
    self: Task,
    *,
    run_id: str,
    repo_full_name: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
) -> dict:
    """
    Main agent task. Orchestrates the full pipeline.

    Phase 2: intake & planning   ✓ implemented
    Phase 3: sandbox execution   ✓ implemented
    Phase 4: self-healing loop     coming
    Phase 6: delivery              coming
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            _run_pipeline(
                run_id=run_id,
                repo_full_name=repo_full_name,
                issue_number=issue_number,
                issue_title=issue_title,
                issue_body=issue_body,
            )
        )
    finally:
        loop.close()


async def _run_pipeline(
    *,
    run_id: str,
    repo_full_name: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
) -> dict:
    logger.info(
        "pipeline.start",
        run_id=run_id,
        repo=repo_full_name,
        issue=issue_number,
    )

    # ── Phase 2: Intake ───────────────────────────────────────────────────────
    from app.services.intake import IntakeService

    context = await IntakeService().run(
        run_id=run_id,
        repo_full_name=repo_full_name,
        issue_number=issue_number,
        issue_title=issue_title,
        issue_body=issue_body,
    )

    if context is None:
        logger.warning("pipeline.aborted_at_intake", run_id=run_id)
        return {"run_id": run_id, "status": "aborted", "phase": "intake"}

    logger.info(
        "pipeline.intake_complete",
        run_id=run_id,
        intent=context.intent,
        risk=context.risk_level,
        plan_steps=len(context.plan_steps),
    )

    # ── Phase 3: Sandbox execution ────────────────────────────────────────────
    from app.services.sandbox import SandboxService

    sandbox = SandboxService()
    sandbox_result = await sandbox.run(
        run_id=run_id,
        issue_context=context,
        retry_count=0,
    )

    if sandbox_result.passed:
        logger.info("pipeline.sandbox_passed", run_id=run_id)
        # TODO Phase 6: push branch, open PR
        return {
            "run_id": run_id,
            "status": "validating",
            "files_changed": len(sandbox_result.patch.files_changed) if sandbox_result.patch else 0,
        }

    # ── Phase 4: Self-healing loop ────────────────────────────────────────────
    # TODO: implemented in Phase 4 — for now surface the failure
    logger.warning(
        "pipeline.sandbox_failed",
        run_id=run_id,
        reason=sandbox_result.failure_reason,
        retry_count=sandbox_result.retry_count,
    )

    return {
        "run_id": run_id,
        "status": "failed",
        "reason": sandbox_result.failure_reason,
        "phase": "sandbox",
    }