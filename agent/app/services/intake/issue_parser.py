from app.core.logging import get_logger
from app.llm import LLMMessage, MessageRole, get_llm_provider
from app.prompts import issue_parser as prompts
from app.schemas.intake import IssueParseResult

logger = get_logger(__name__)


class IssueParser:
    """Calls the configured LLM provider to parse a GitHub issue into a
    structured IssueParseResult."""

    async def parse(
        self,
        repo_full_name: str,
        issue_number: int,
        issue_title: str,
        issue_body: str,
    ) -> IssueParseResult:
        raw_messages = prompts.build_messages(
            repo_full_name=repo_full_name,
            issue_number=issue_number,
            issue_title=issue_title,
            issue_body=issue_body,
        )
        messages = [LLMMessage(role=m["role"], content=m["content"]) for m in raw_messages]

        llm = get_llm_provider()
        result = await llm.complete_structured(
            messages=messages,
            response_model=IssueParseResult,
        )

        logger.info(
            "issue_parser.done",
            repo=repo_full_name,
            issue=issue_number,
            intent=result.intent,
            confidence=result.confidence,
        )
        return result