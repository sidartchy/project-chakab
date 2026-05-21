import uuid
from typing import Any

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import IssueIntent, RiskLevel, RunStatus


class AgentRun(Base, UUIDMixin, TimestampMixin):
    """Represents one end-to-end attempt to resolve a GitHub issue."""

    __tablename__ = "agent_runs"

    # GitHub identifiers
    repo_full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    issue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_title: Mapped[str] = mapped_column(String(512), nullable=False)
    delivery_id: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True,
        comment="GitHub webhook delivery_id for idempotency"
    )

    # Run state
    status: Mapped[RunStatus] = mapped_column(
        SAEnum(RunStatus, name="run_status"),
        nullable=False,
        default=RunStatus.pending,
        index=True,
    )

    # Intake outputs (populated after planning phase)
    intent: Mapped[IssueIntent | None] = mapped_column(
        SAEnum(IssueIntent, name="issue_intent"), nullable=True
    )
    risk_level: Mapped[RiskLevel | None] = mapped_column(
        SAEnum(RiskLevel, name="risk_level"), nullable=True
    )

    # Structured context (JSON blobs — typed in Phase 2)
    issue_context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    plan_steps: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)

    # Execution outputs
    patch_diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_logs_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Delivery outputs
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AgentRun id={self.id} repo={self.repo_full_name} "
            f"issue=#{self.issue_number} status={self.status}>"
        )