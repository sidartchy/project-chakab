from celery import Task
from celery.utils.log import get_task_logger

from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


class AgentTask(Task):
    """Base task class with common error handling."""

    abstract = True

    def on_failure(self, exc: Exception, task_id: str, args: tuple, kwargs: dict, einfo) -> None:  # type: ignore[override]
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
    max_retries=3,
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
    Main agent task. Orchestrates the full pipeline:
      Phase 2: intake & planning
      Phase 3: sandbox execution
      Phase 4: self-healing loop
      Phase 6: delivery

    Currently a stub — logs receipt and returns pending status.
    """
    logger.info(
        "process_issue.received",
        run_id=run_id,
        repo=repo_full_name,
        issue=issue_number,
    )

    # TODO Phase 2: call intake service (issue parser, risk classifier, planner)
    # TODO Phase 3: spawn sandbox, apply patch, run CI
    # TODO Phase 4: self-healing loop
    # TODO Phase 6: push branch, open PR

    return {
        "run_id": run_id,
        "status": "pending",
        "message": "Task received — full pipeline not yet implemented",
    }