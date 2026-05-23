SYSTEM = """\
You are a senior software engineer creating an implementation plan for a junior agent.
The agent will execute each step sequentially inside an isolated sandbox.

Rules:
- Each step must target exactly one file.
- action must be one of: edit | add | delete.
- Steps must be ordered so later steps can depend on earlier ones.
- test_hint should name a specific test file or describe what test to write/run.
- Do not include steps for running tests — the CI runner handles that automatically.
- Maximum 8 steps. If more are needed, the issue is too broad for the agent.
- Be specific enough that a junior engineer could execute each step without asking questions.
"""

USER_TEMPLATE = """\
Repository: {repo_full_name}
Issue #{issue_number}: {issue_title}

Description: {cleaned_description}

Acceptance criteria:
{criteria_list}

Relevant files (with snippets):
{file_summaries}

Produce an ordered implementation plan.
"""


def build_messages(
    repo_full_name: str,
    issue_number: int,
    issue_title: str,
    cleaned_description: str,
    acceptance_criteria: list[str],
    relevant_files: list[dict],  # list of {path, snippet, language}
) -> list[dict[str, str]]:
    criteria_list = "\n".join(f"- {c}" for c in acceptance_criteria)

    file_summaries_parts = []
    for f in relevant_files:
        snippet = f.get("snippet", "").strip()
        truncated = snippet[:800] + "..." if len(snippet) > 800 else snippet
        file_summaries_parts.append(
            f"### {f['path']} ({f.get('language', 'unknown')})\n```\n{truncated}\n```"
        )
    file_summaries = "\n\n".join(file_summaries_parts) or "No relevant files identified."

    return [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": USER_TEMPLATE.format(
                repo_full_name=repo_full_name,
                issue_number=issue_number,
                issue_title=issue_title,
                cleaned_description=cleaned_description,
                criteria_list=criteria_list,
                file_summaries=file_summaries,
            ),
        },
    ]