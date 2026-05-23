SYSTEM = """\
You are a code review safety officer evaluating whether a GitHub issue is safe
for an autonomous agent to resolve without human supervision.

Risk levels:
- low:    Clearly scoped, affects ≤5 files, no infrastructure changes, no auth/security code.
- medium: Touches more files or has some uncertainty, but still bounded.
- high:   Broad refactor, touches infra/migrations/auth, unclear scope, or could break many things.

Be conservative — when in doubt, go higher.
"""

USER_TEMPLATE = """\
Repository: {repo_full_name}
Issue: {issue_title}

Parsed intent: {intent}
Cleaned description: {cleaned_description}
Acceptance criteria:
{criteria_list}

Estimated files mentioned: {mentioned_files}

Assess the risk level of letting an autonomous agent resolve this issue.
Return estimated_files_affected as your best guess of how many files will need changes.
"""


def build_messages(
    repo_full_name: str,
    issue_title: str,
    intent: str,
    cleaned_description: str,
    acceptance_criteria: list[str],
    mentioned_files: list[str],
) -> list[dict[str, str]]:
    criteria_list = "\n".join(f"- {c}" for c in acceptance_criteria)
    files_str = ", ".join(mentioned_files) if mentioned_files else "none explicitly mentioned"

    return [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": USER_TEMPLATE.format(
                repo_full_name=repo_full_name,
                issue_title=issue_title,
                intent=intent,
                cleaned_description=cleaned_description,
                criteria_list=criteria_list,
                mentioned_files=files_str,
            ),
        },
    ]