SYSTEM = """\
You are an expert software engineer generating a unified diff patch to resolve a GitHub issue.

Rules:
- Output ONLY a valid unified diff (--- / +++ / @@ format). No explanation, no markdown fences.
- Every file you modify MUST appear in the provided plan steps. Do not touch other files.
- Do not change whitespace or formatting outside the lines you are directly modifying.
- Do not add, remove, or modify import statements unless the plan explicitly requires it.
- Do not modify test files unless the plan step targets a test file.
- Keep changes minimal — fix exactly what the issue describes, nothing more.
- The diff must apply cleanly with: patch -p1 < changes.patch
"""

USER_TEMPLATE = """\
Repository: {repo_full_name}
Issue #{issue_number}: {issue_title}

Description: {cleaned_description}

Acceptance criteria:
{criteria_list}

Implementation plan:
{plan_steps}

Current file contents:
{file_contents}

Generate the unified diff to implement this plan.
"""


def build_messages(
    repo_full_name: str,
    issue_number: int,
    issue_title: str,
    cleaned_description: str,
    acceptance_criteria: list[str],
    plan_steps: list[dict],
    file_contents: dict[str, str],  # {path: content}
) -> list[dict[str, str]]:
    criteria_list = "\n".join(f"- {c}" for c in acceptance_criteria)

    steps_text = "\n".join(
        f"{s['order']}. [{s['action'].upper()}] {s['file_path']}: {s['description']}"
        for s in plan_steps
    )

    file_parts = []
    for path, content in file_contents.items():
        truncated = content[:3000] + "\n... (truncated)" if len(content) > 3000 else content
        file_parts.append(f"### {path}\n```\n{truncated}\n```")
    file_contents_str = "\n\n".join(file_parts) if file_parts else "No existing files to show."

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
                plan_steps=steps_text,
                file_contents=file_contents_str,
            ),
        },
    ]