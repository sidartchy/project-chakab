from pydantic import BaseModel, Field


class GitHubUser(BaseModel):
    login: str
    id: int


class GitHubRepository(BaseModel):
    id: int
    full_name: str
    private: bool
    clone_url: str
    default_branch: str


class GitHubIssue(BaseModel):
    number: int
    title: str
    body: str | None = None
    state: str
    html_url: str
    user: GitHubUser
    labels: list[dict] = Field(default_factory=list)
    assignee: GitHubUser | None = None


class GitHubIssueEvent(BaseModel):
    """Payload for issues webhook events (assigned, labeled, opened, etc.)"""

    action: str
    issue: GitHubIssue
    repository: GitHubRepository
    sender: GitHubUser
    assignee: GitHubUser | None = None  # present on 'assigned' action

    @property
    def label_names(self) -> list[str]:
        return [label.get("name", "") for label in self.issue.labels]