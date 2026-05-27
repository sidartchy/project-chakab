import uuid

from github import Auth, Github
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.agent_run import AgentRun
from app.models.enums import RunStatus
from app.schemas.intake import IssueContext
from app.schemas.sandbox import CIResult, PatchResult, SandboxResult
from app.services.sandbox.ci_runner import CIRunner
from app.services.sandbox.log_storage import LogStorage
from app.services.sandbox.patch_applicator import PatchApplicator
from app.services.sandbox.sandbox_manager import SandboxManager

logger = get_logger(__name__)


class SandboxService:
    """Orchestrates one sandbox execution attempt.

    Called by the Celery task for each attempt (initial + retries).
    Returns a SandboxResult — the caller (Phase 4) decides whether to
    retry or proceed to delivery.
    """

    def __init__(self) -> None:
        self._manager = SandboxManager()
        self._log_storage = LogStorage()

    async def run(
        self,
        run_id: str,
        issue_context: IssueContext,
        retry_count: int = 0,
    ) -> SandboxResult:
        repo_url = f"https://github.com/{issue_context.repo_full_name}.git"

        # Inject token into clone URL so private repos work
        if settings.github_token:
            repo_url = (
                f"https://x-access-token:{settings.github_token}"
                f"@github.com/{issue_context.repo_full_name}.git"
            )

        patch_applicator = PatchApplicator(self._manager)
        ci_runner = CIRunner(self._manager)

        try:
            with self._manager.create(run_id, repo_url) as ctx:
                # ── Patch ──────────────────────────────────────────────────
                logger.info("sandbox_service.applying_patch", run_id=run_id)
                try:
                    patch = await patch_applicator.apply(ctx, issue_context)
                except Exception as exc:
                    return await self._fail(
                        run_id,
                        reason=f"Patch application failed: {exc}",
                        retry_count=retry_count,
                    )

                # ── CI ─────────────────────────────────────────────────────
                logger.info("sandbox_service.running_ci", run_id=run_id)
                ci = ci_runner.run(ctx)

                # Persist logs
                log_url = await self._save_logs(run_id, ci)
                ci = ci.model_copy(update={"log_url": log_url})

                if ci.passed:
                    return await self._succeed(run_id, patch, ci, retry_count)
                else:
                    return SandboxResult(
                        passed=False,
                        patch=patch,
                        ci=ci,
                        failure_reason=self._describe_failure(ci),
                        retry_count=retry_count,
                    )

        except Exception as exc:
            logger.exception("sandbox_service.unexpected_error", run_id=run_id, exc_info=exc)
            return await self._fail(
                run_id,
                reason=f"Unexpected sandbox error: {exc}",
                retry_count=retry_count,
            )

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _succeed(
        self,
        run_id: str,
        patch: PatchResult,
        ci: CIResult,
        retry_count: int,
    ) -> SandboxResult:
        async with AsyncSessionLocal() as db:
            run = await self._get_run(db, run_id)
            if run:
                run.patch_diff = patch.diff
                run.test_logs_url = ci.log_url
                run.retry_count = retry_count
                run.status = RunStatus.validating
                await db.commit()

        logger.info(
            "sandbox_service.succeeded",
            run_id=run_id,
            files_changed=len(patch.files_changed),
        )
        return SandboxResult(passed=True, patch=patch, ci=ci, retry_count=retry_count)

    async def _fail(
        self, run_id: str, reason: str, retry_count: int
    ) -> SandboxResult:
        logger.warning("sandbox_service.failed", run_id=run_id, reason=reason)
        return SandboxResult(
            passed=False,
            failure_reason=reason,
            retry_count=retry_count,
        )

    async def _save_logs(self, run_id: str, ci: CIResult) -> str:
        try:
            return await self._log_storage.save(
                run_id=run_id,
                phase="ci",
                content=ci.combined_logs,
            )
        except Exception as exc:
            logger.warning("sandbox_service.log_save_failed", error=str(exc))
            return ""

    @staticmethod
    def _describe_failure(ci: CIResult) -> str:
        failed = ci.failed_phase
        if not failed:
            return "CI failed for unknown reason"
        snippet = (failed.stdout + "\n" + failed.stderr).strip()[-2000:]
        return (
            f"Phase '{failed.phase}' failed (exit {failed.exit_code})"
            + (", timed out" if failed.timed_out else "")
            + f":\n{snippet}"
        )

    @staticmethod
    async def _get_run(db: AsyncSession, run_id: str) -> AgentRun | None:
        from sqlalchemy import select
        result = await db.execute(
            select(AgentRun).where(AgentRun.id == uuid.UUID(run_id))
        )
        return result.scalar_one_or_none()