from app.core.logging import get_logger
from app.llm import LLMMessage, get_llm_provider
from app.prompts import plan_generator as prompts
from app.schemas.intake import FileRef, IssueParseResult, PlanResult

logger = get_logger(__name__)


class PlanGenerator:
    """Calls the LLM to produce an ordered list of PlanSteps given the
    parsed issue and relevant files."""

    async def generate(
        self,
        repo_full_name: str,
        issue_number: int,
        issue_title: str,
        parse_result: IssueParseResult,
        relevant_files: list[FileRef],
    ) -> PlanResult:
        file_dicts = [
            {
                "path": f.path,
                "snippet": f.snippet,
                "language": f.language,
            }
            for f in relevant_files
        ]

        raw_messages = prompts.build_messages(
            repo_full_name=repo_full_name,
            issue_number=issue_number,
            issue_title=issue_title,
            cleaned_description=parse_result.cleaned_description,
            acceptance_criteria=parse_result.acceptance_criteria,
            relevant_files=file_dicts,
        )
        messages = [LLMMessage(role=m["role"], content=m["content"]) for m in raw_messages]

        llm = get_llm_provider()
        result = await llm.complete_structured(
            messages=messages,
            response_model=PlanResult,
        )

        logger.info(
            "plan_generator.done",
            repo=repo_full_name,
            issue=issue_number,
            steps=len(result.steps),
            summary=result.summary,
        )
        return result