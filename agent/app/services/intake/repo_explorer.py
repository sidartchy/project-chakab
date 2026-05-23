from github import Auth, Github
from github.Repository import Repository

from app.config import settings
from app.core.logging import get_logger
from app.schemas.intake import FileRef, IssueParseResult

logger = get_logger(__name__)

# Extensions we'll attempt to read content for
_TEXT_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs",
    ".java", ".rb", ".php", ".cs", ".cpp", ".c", ".h",
    ".md", ".yaml", ".yml", ".toml", ".json",
}

# Files/dirs to always skip (noise)
_SKIP_PREFIXES = (
    "node_modules/", ".git/", "dist/", "build/", "__pycache__/",
    ".venv/", "venv/", ".mypy_cache/", ".ruff_cache/",
)

# Max files to return
_TOP_K = 8
# Max chars of file content to include as snippet
_SNIPPET_CHARS = 1500


class RepoExplorer:
    """Fetches the repository file tree from GitHub and ranks files by
    relevance to the parsed issue using keyword scoring.

    tree-sitter symbol extraction is wired in here as an optional upgrade —
    currently falls back to plain keyword matching which is sufficient for
    Phase 2.
    """

    def __init__(self) -> None:
        auth = Auth.Token(settings.github_token)
        self._gh = Github(auth=auth)

    async def explore(
        self,
        repo_full_name: str,
        parse_result: IssueParseResult,
    ) -> list[FileRef]:
        repo = self._gh.get_repo(repo_full_name)
        all_files = self._get_file_tree(repo)

        keywords = self._extract_keywords(parse_result)
        scored = self._score_files(all_files, keywords, parse_result.mentioned_files)

        # Fetch content for top candidates
        top_files = scored[:_TOP_K]
        result: list[FileRef] = []
        for path, score in top_files:
            snippet, language = self._fetch_snippet(repo, path)
            result.append(
                FileRef(
                    path=path,
                    relevance_score=round(score, 3),
                    snippet=snippet,
                    language=language,
                )
            )

        logger.info(
            "repo_explorer.done",
            repo=repo_full_name,
            total_files=len(all_files),
            top_k=len(result),
        )
        return result

    # ── private helpers ───────────────────────────────────────────────────────

    def _get_file_tree(self, repo: Repository) -> list[str]:
        tree = repo.get_git_tree(repo.default_branch, recursive=True)
        paths = []
        for item in tree.tree:
            if item.type != "blob":
                continue
            if any(item.path.startswith(p) for p in _SKIP_PREFIXES):
                continue
            if not any(item.path.endswith(ext) for ext in _TEXT_EXTENSIONS):
                continue
            paths.append(item.path)
        return paths

    def _extract_keywords(self, parse_result: IssueParseResult) -> set[str]:
        """Build a keyword set from the parsed issue for relevance scoring."""
        tokens: set[str] = set()
        for text in [parse_result.cleaned_description, *parse_result.acceptance_criteria]:
            for word in text.lower().split():
                cleaned = word.strip(".,;:()[]{}\"'")
                if len(cleaned) > 3:
                    tokens.add(cleaned)
        return tokens

    def _score_files(
        self,
        paths: list[str],
        keywords: set[str],
        mentioned_files: list[str],
    ) -> list[tuple[str, float]]:
        mentioned_set = {f.lower() for f in mentioned_files}
        scored: list[tuple[str, float]] = []

        for path in paths:
            path_lower = path.lower()
            score = 0.0

            # Explicitly mentioned in issue → strong signal
            if path_lower in mentioned_set or any(m in path_lower for m in mentioned_set):
                score += 1.0

            # Keyword match against path segments
            path_tokens = set(path_lower.replace("/", " ").replace("_", " ").split())
            overlap = len(keywords & path_tokens)
            score += overlap * 0.15

            if score > 0:
                scored.append((path, min(score, 1.0)))

        # Sort descending, return top results
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _fetch_snippet(self, repo: Repository, path: str) -> tuple[str, str]:
        """Fetch the first _SNIPPET_CHARS characters of a file."""
        try:
            content_file = repo.get_contents(path)
            if isinstance(content_file, list):
                return "", "unknown"
            decoded = content_file.decoded_content.decode("utf-8", errors="replace")
            snippet = decoded[:_SNIPPET_CHARS]
            language = path.rsplit(".", 1)[-1] if "." in path else "unknown"
            return snippet, language
        except Exception as exc:
            logger.warning("repo_explorer.fetch_failed", path=path, error=str(exc))
            return "", "unknown"