from pydantic import BaseModel, Field

from app.models.enums import IssueIntent, RiskLevel


class FileRef(BaseModel):
    """A repository file identified as relevant to the issue."""
    path: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    snippet: str = Field(default="", description="First ~40 lines of the file")
    language: str = Field(default="unknown")


class PlanStep(BaseModel):
    """A single concrete action the agent should take."""
    order: int
    file_path: str
    action: str = Field(description="One of: edit | add | delete")
    description: str = Field(description="Plain-English explanation of the change")
    test_hint: str = Field(
        default="",
        description="Suggestion for what test to run or write to verify this step",
    )


class IssueParseResult(BaseModel):
    """LLM output from the issue parser."""
    intent: IssueIntent
    cleaned_description: str = Field(
        description="Concise restatement of what needs to be done"
    )
    acceptance_criteria: list[str] = Field(
        min_length=1,
        max_length=6,
        description="Concrete, testable conditions for the issue to be considered resolved",
    )
    mentioned_files: list[str] = Field(
        default_factory=list,
        description="File paths explicitly mentioned in the issue body",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model's confidence that the issue is well-scoped and understandable",
    )


class RiskAssessment(BaseModel):
    """Combined output of rule-based + LLM risk classification."""
    risk_level: RiskLevel
    reason: str
    blocked_patterns_matched: list[str] = Field(default_factory=list)
    estimated_files_affected: int = Field(ge=0)


class IssueContext(BaseModel):
    """Full intake context passed to the plan generator and beyond."""
    repo_full_name: str
    issue_number: int
    issue_title: str
    issue_body: str

    # Populated by IssueParser
    intent: IssueIntent
    cleaned_description: str
    acceptance_criteria: list[str]
    parse_confidence: float

    # Populated by RiskClassifier
    risk_level: RiskLevel
    risk_reason: str

    # Populated by RepoExplorer
    relevant_files: list[FileRef]

    # Populated by PlanGenerator
    plan_steps: list[PlanStep]


class PlanResult(BaseModel):
    """LLM output from the plan generator."""
    steps: list[PlanStep]
    summary: str = Field(description="One-sentence summary of the overall approach")