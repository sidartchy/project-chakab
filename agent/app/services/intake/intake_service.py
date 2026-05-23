import uuid

from github import Auth, Github
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.agent_run import AgentRun
from app.models.enums import RiskLevel, RunStatus
from app.schemas.intake import IssueContext
from app.services.intake.issue_parser import IssueParser
from app.services.intake.plan_generator import PlanGenerator
from app.services.intake.repo_explorer import RepoExplorer
from app.services.intake.risk_classifier import RiskClassifier

logger = get_logger(__name__)


class IntakeService:
    """Orchestrates the full intake pipeline for a single AgentRun:

        IssueParser → RiskClassifier → RepoExplorer → PlanGenerator

    Updates AgentRun status at each step. On high-risk or low-confidence
    issues, marks the run as aborted and posts a GitHub comment.
    """

    def __init__(self) -> None:
        self._parser = IssueParser()
        self._classifier = RiskClassifier()
        self._explorer = RepoExplorer()
        self._planner = PlanGenerator()

    async def run(
        self,
        run_id: str,
        repo_full_name: str,
        issue_number: int,
        issue_title: str,
        issue_body: str,
    ) -> IssueContext | None:
        """Execute the intake pipeline. Returns IssueContext on success,
        None if the run was aborted."""

        async with AsyncSessionLocal() as db:
            agent_run = await self._get_run(db, run_id)
            if not agent_run:
                logger.error("intake.run_not_found", run_id=run_id)
                return None

            await self._set_status(db, agent_run, RunStatus.planning)

            # ── Step 1: parse issue ───────────────────────────────────────────
            logger.info("intake.parsing", run_id=run_id)
            parse_result = await self._parser.parse(
                repo_full_name=repo_full_name,
                issue_number=issue_number,
                issue_title=issue_title,
                issue_body=issue_body,
            )

            # Abort if model isn't confident it understands the issue
            if parse_result.confidence < 0.5:
                return await self._abort(
                    db, agent_run,
                    reason=(
                        f"Issue is ambiguous or too broad "
                        f"(parse confidence: {parse_result.confidence:.2f}). "
                        "Please clarify the issue and re-assign."
                    ),
                    repo_full_name=repo_full_name,
                    issue_number=issue_number,
                )

            agent_run.intent = parse_result.intent
            agent_run.issue_context = parse_result.model_dump()
            await db.flush()

            # ── Step 2: classify risk ─────────────────────────────────────────
            logger.info("intake.classifying_risk", run_id=run_id)
            risk = await self._classifier.classify(
                repo_full_name=repo_full_name,
                issue_title=issue_title,
                parse_result=parse_result,
            )

            agent_run.risk_level = risk.risk_level
            await db.flush()

            if risk.risk_level == RiskLevel.high:
                return await self._abort(
                    db, agent_run,
                    reason=f"Risk level HIGH — {risk.reason}",
                    repo_full_name=repo_full_name,
                    issue_number=issue_number,
                )

            # ── Step 3: explore repo ──────────────────────────────────────────
            logger.info("intake.exploring_repo", run_id=run_id)
            relevant_files = await self._explorer.explore(
                repo_full_name=repo_full_name,
                parse_result=parse_result,
            )

            # ── Step 4: generate plan ─────────────────────────────────────────
            logger.info("intake.generating_plan", run_id=run_id)
            plan = await self._planner.generate(
                repo_full_name=repo_full_name,
                issue_number=issue_number,
                issue_title=issue_title,
                parse_result=parse_result,
                relevant_files=relevant_files,
            )

            # Persist plan steps
            agent_run.plan_steps = [s.model_dump() for s in plan.steps]
            await self._set_status(db, agent_run, RunStatus.executing)

            context = IssueContext(
                repo_full_name=repo_full_name,
                issue_number=issue_number,
                issue_title=issue_title,
                issue_body=issue_body,
                intent=parse_result.intent,
                cleaned_description=parse_result.cleaned_description,
                acceptance_criteria=parse_result.acceptance_criteria,
                parse_confidence=parse_result.confidence,
                risk_level=risk.risk_level,
                risk_reason=risk.reason,
                relevant_files=relevant_files,
                plan_steps=plan.steps,
            )

            logger.info(
                "intake.complete",
                run_id=run_id,
                intent=context.intent,
                risk=context.risk_level,
                files=len(relevant_files),
                steps=len(plan.steps),
            )
            return context

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _get_run(self, db: AsyncSession, run_id: str) -> AgentRun | None:
        result = await db.execute(
            select(AgentRun).where(AgentRun.id == uuid.UUID(run_id))
        )
        return result.scalar_one_or_none()

    async def _set_status(
        self, db: AsyncSession, run: AgentRun, status: RunStatus
    ) -> None:
        run.status = status
        await db.flush()

    async def _abort(
        self,
        db: AsyncSession,
        run: AgentRun,
        reason: str,
        repo_full_name: str,
        issue_number: int,
    ) -> None:
        run.status = RunStatus.aborted
        run.failure_reason = reason
        await db.commit()

        logger.warning(
            "intake.aborted",
            run_id=str(run.id),
            reason=reason,
        )

        # Post a comment on the issue so the author knows why it was skipped
        self._post_github_comment(
            repo_full_name=repo_full_name,
            issue_number=issue_number,
            reason=reason,
        )
        return None

    def _post_github_comment(
        self, repo_full_name: str, issue_number: int, reason: str
    ) -> None:
        try:
            auth = Auth.Token(settings.github_token)
            gh = Github(auth=auth)
            repo = gh.get_repo(repo_full_name)
            issue = repo.get_issue(issue_number)
            issue.create_comment(
                f"🤖 **Agent skipped this issue**\n\n"
                f"**Reason:** {reason}\n\n"
                f"Please address the above and re-assign to the agent."
            )
        except Exception as exc:
            logger.warning(
                "intake.github_comment_failed",
                repo=repo_full_name,
                issue=issue_number,
                error=str(exc),
            )