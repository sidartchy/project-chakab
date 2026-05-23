import re

from app.core.logging import get_logger
from app.llm import LLMMessage, get_llm_provider
from app.models.enums import RiskLevel
from app.prompts import risk_classifier as prompts
from app.schemas.intake import IssueParseResult, RiskAssessment

logger = get_logger(__name__)

# Paths/patterns that immediately flag an issue as high risk.
# The agent must never touch these without explicit human supervision.
_BLOCKED_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"migrations?/",
        r"alembic/",
        r"\.env",
        r"settings\.py",
        r"config/.*prod",
        r"infra/",
        r"terraform/",
        r"dockerfile",
        r"docker-compose",
        r"\.github/workflows",
        r"auth.*\.(py|ts|js)",
        r"security.*\.(py|ts|js)",
        r"password",
        r"secret",
        r"pyproject\.toml",
        r"package\.json",
        r"requirements.*\.txt",
    ]
]


class RiskClassifier:
    """Two-pass risk classification.

    Pass 1 (rule-based): checks mentioned files and issue text against a
    blocklist of sensitive patterns → instant high risk if matched.

    Pass 2 (LLM): asks the model to estimate blast radius and assign a level.
    The final level is the maximum of both passes.
    """

    async def classify(
        self,
        repo_full_name: str,
        issue_title: str,
        parse_result: IssueParseResult,
    ) -> RiskAssessment:

        # ── Pass 1: rule-based ────────────────────────────────────────────────
        blocked_matches = self._check_blocked_patterns(
            files=parse_result.mentioned_files,
            text=f"{issue_title} {parse_result.cleaned_description}",
        )

        if blocked_matches:
            logger.warning(
                "risk_classifier.blocked_pattern",
                repo=repo_full_name,
                patterns=blocked_matches,
            )
            return RiskAssessment(
                risk_level=RiskLevel.high,
                reason="Issue mentions sensitive files or patterns that the agent must not modify.",
                blocked_patterns_matched=blocked_matches,
                estimated_files_affected=len(parse_result.mentioned_files),
            )

        # ── Pass 2: LLM ───────────────────────────────────────────────────────
        raw_messages = prompts.build_messages(
            repo_full_name=repo_full_name,
            issue_title=issue_title,
            intent=parse_result.intent,
            cleaned_description=parse_result.cleaned_description,
            acceptance_criteria=parse_result.acceptance_criteria,
            mentioned_files=parse_result.mentioned_files,
        )
        messages = [LLMMessage(role=m["role"], content=m["content"]) for m in raw_messages]

        llm = get_llm_provider()
        assessment = await llm.complete_structured(
            messages=messages,
            response_model=RiskAssessment,
        )

        logger.info(
            "risk_classifier.done",
            repo=repo_full_name,
            risk_level=assessment.risk_level,
            files_affected=assessment.estimated_files_affected,
        )
        return assessment

    def _check_blocked_patterns(self, files: list[str], text: str) -> list[str]:
        matched: list[str] = []
        combined = " ".join(files) + " " + text
        for pattern in _BLOCKED_PATTERNS:
            if pattern.search(combined):
                matched.append(pattern.pattern)
        return matched