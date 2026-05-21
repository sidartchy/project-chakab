import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agent_run import AgentRun
from app.models.enums import RunStatus
from app.schemas.agent_run import WebhookAcceptedResponse
from app.schemas.webhook import GitHubIssueEvent
from app.workers.tasks import process_issue

logger = get_logger(__name__)

# Label that must be present on an issue for the agent to pick it up
AGENT_TRIGGER_LABEL = "agent-resolve"

# GitHub issue actions we care about
TRIGGER_ACTIONS = {"labeled", "assigned"}


class WebhookService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def handle_issue_event(
        self,
        event: GitHubIssueEvent,
        delivery_id: str,
    ) -> WebhookAcceptedResponse | None:
        """Process a GitHub issues webhook event.

        Returns a response if a new AgentRun was created, None if the event
        was intentionally skipped (wrong action, missing label, etc.).
        """
        if not self._should_trigger(event):
            logger.info(
                "webhook.skipped",
                action=event.action,
                issue=event.issue.number,
                repo=event.repository.full_name,
            )
            return None

        # Idempotency: don't create a duplicate run for the same delivery
        existing = await self._find_by_delivery_id(delivery_id)
        if existing:
            logger.info("webhook.duplicate", delivery_id=delivery_id, run_id=str(existing.id))
            return WebhookAcceptedResponse(
                message="Already processing",
                run_id=existing.id,
                delivery_id=delivery_id,
            )

        run = AgentRun(
            repo_full_name=event.repository.full_name,
            issue_number=event.issue.number,
            issue_title=event.issue.title,
            delivery_id=delivery_id,
            status=RunStatus.pending,
        )
        self.db.add(run)
        await self.db.flush()  # get the UUID before enqueueing

        # Enqueue background task (Celery)
        process_issue.delay(
            run_id=str(run.id),
            repo_full_name=event.repository.full_name,
            issue_number=event.issue.number,
            issue_title=event.issue.title,
            issue_body=event.issue.body or "",
        )

        logger.info(
            "webhook.accepted",
            run_id=str(run.id),
            repo=event.repository.full_name,
            issue=event.issue.number,
        )

        return WebhookAcceptedResponse(
            message="Issue queued for processing",
            run_id=run.id,
            delivery_id=delivery_id,
        )

    def _should_trigger(self, event: GitHubIssueEvent) -> bool:
        if event.action not in TRIGGER_ACTIONS:
            return False
        if AGENT_TRIGGER_LABEL not in event.label_names:
            return False
        if event.issue.state != "open":
            return False
        return True

    async def _find_by_delivery_id(self, delivery_id: str) -> AgentRun | None:
        from sqlalchemy import select

        result = await self.db.execute(
            select(AgentRun).where(AgentRun.delivery_id == delivery_id)
        )
        return result.scalar_one_or_none()