from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import IssueIntent, RiskLevel
from app.schemas.intake import IssueParseResult, RiskAssessment


# ── IssueParser ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_issue_parser_calls_llm_and_returns_result(monkeypatch):
    mock_result = IssueParseResult(
        intent=IssueIntent.bug_fix,
        cleaned_description="Fix the null pointer in UserService.get_user()",
        acceptance_criteria=["get_user returns None instead of raising", "existing tests pass"],
        mentioned_files=["app/services/user_service.py"],
        confidence=0.92,
    )

    mock_provider = AsyncMock()
    mock_provider.complete_structured = AsyncMock(return_value=mock_result)

    with patch("app.services.intake.issue_parser.get_llm_provider", return_value=mock_provider):
        from app.services.intake.issue_parser import IssueParser
        parser = IssueParser()
        result = await parser.parse(
            repo_full_name="org/repo",
            issue_number=42,
            issue_title="NullPointerError in get_user",
            issue_body="Calling get_user() with a missing user raises NPE instead of returning None.",
        )

    assert result.intent == IssueIntent.bug_fix
    assert result.confidence == 0.92
    assert len(result.acceptance_criteria) == 2


# ── RiskClassifier ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_risk_classifier_blocks_migration_files():
    parse_result = IssueParseResult(
        intent=IssueIntent.bug_fix,
        cleaned_description="Fix a bug",
        acceptance_criteria=["it works"],
        mentioned_files=["migrations/0001_initial.py"],
        confidence=0.9,
    )

    from app.services.intake.risk_classifier import RiskClassifier
    classifier = RiskClassifier()
    result = await classifier.classify(
        repo_full_name="org/repo",
        issue_title="Fix migration",
        parse_result=parse_result,
    )

    assert result.risk_level == RiskLevel.high
    assert len(result.blocked_patterns_matched) > 0


@pytest.mark.asyncio
async def test_risk_classifier_calls_llm_when_no_blocked_patterns():
    parse_result = IssueParseResult(
        intent=IssueIntent.bug_fix,
        cleaned_description="Fix a null check in user service",
        acceptance_criteria=["returns None on missing user"],
        mentioned_files=["app/services/user_service.py"],
        confidence=0.9,
    )

    mock_result = RiskAssessment(
        risk_level=RiskLevel.low,
        reason="Small, well-scoped bug fix in a single service file.",
        estimated_files_affected=1,
    )

    mock_provider = AsyncMock()
    mock_provider.complete_structured = AsyncMock(return_value=mock_result)

    with patch("app.services.intake.risk_classifier.get_llm_provider", return_value=mock_provider):
        from app.services.intake.risk_classifier import RiskClassifier
        classifier = RiskClassifier()
        result = await classifier.classify(
            repo_full_name="org/repo",
            issue_title="Fix null check",
            parse_result=parse_result,
        )

    assert result.risk_level == RiskLevel.low
    mock_provider.complete_structured.assert_called_once()


# ── RiskClassifier blocked pattern edge cases ──────────────────────────────────

@pytest.mark.parametrize("path", [
    "migrations/0001_initial.py",
    "alembic/versions/abc123.py",
    ".env.production",
    "infra/main.tf",
    "terraform/variables.tf",
    ".github/workflows/deploy.yml",
])
@pytest.mark.asyncio
async def test_risk_classifier_blocks_sensitive_paths(path):
    parse_result = IssueParseResult(
        intent=IssueIntent.bug_fix,
        cleaned_description="something",
        acceptance_criteria=["works"],
        mentioned_files=[path],
        confidence=0.9,
    )

    from app.services.intake.risk_classifier import RiskClassifier
    result = await RiskClassifier().classify("org/repo", "Fix thing", parse_result)
    assert result.risk_level == RiskLevel.high