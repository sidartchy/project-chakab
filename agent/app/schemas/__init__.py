import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.enums import IssueIntent, RiskLevel, RunStatus


class AgentRunResponse(BaseModel):
    id: uuid.UUID
    repo_full_name: str
    issue_number: int
    issue_title: str
    status: RunStatus
    intent: IssueIntent | None
    risk_level: RiskLevel | None
    retry_count: int
    pr_url: str | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WebhookAcceptedResponse(BaseModel):
    message: str
    run_id: uuid.UUID
    delivery_id: str