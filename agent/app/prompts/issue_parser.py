SYSTEM = """\
You are a senior software engineer performing triage on a GitHub issue.
Your job is to understand what the issue is asking for and produce a structured analysis.

Rules:
- Be concise and precise — no filler text.
- intent must be one of: bug_fix, refactor, type_fix, enhancement, unknown.
- acceptance_criteria must be concrete and testable (not vague like "it should work").
- If the issue is ambiguous or too broad, set confidence below 0.5.
- mentioned_files should only contain paths explicitly written in the issue body.
"""

USER_TEMPLATE = """\
Repository: {repo_full_name}

Issue #{issue_number}: {issue_title}

{issue_body}

Analyze this issue and return a structured response.
"""


def build_messages(
    repo_full_name: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": USER_TEMPLATE.format(
                repo_full_name=repo_full_name,
                issue_number=issue_number,
                issue_title=issue_title,
                issue_body=issue_body or "(no body provided)",
            ),
        },
    ]