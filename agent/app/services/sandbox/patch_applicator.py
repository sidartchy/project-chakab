import os
import re
import tempfile

from app.core.logging import get_logger
from app.llm import LLMMessage, LLMConfig, MessageRole, get_llm_provider
from app.prompts import patch_generator as prompts
from app.schemas.intake import IssueContext
from app.schemas.sandbox import PatchResult
from app.services.sandbox.sandbox_manager import ExecResult, SandboxContext, SandboxManager

logger = get_logger(__name__)

# Hard limits on the diff to prevent runaway changes
_MAX_FILES_CHANGED = 5
_MAX_LINES_CHANGED = 500


class PatchApplicator:
    """Generates a unified diff via LLM and applies it inside the sandbox.

    Flow:
      1. Read current content of every file in plan_steps from sandbox
      2. Call LLM with file contents + IssueContext → raw diff string
      3. Validate the diff (scope, size, no path traversal)
      4. Write diff to a temp file inside the sandbox
      5. Apply with `patch -p1`
      6. Return PatchResult with the applied diff and stats
    """

    def __init__(self, manager: SandboxManager) -> None:
        self._manager = manager

    async def apply(
        self,
        ctx: SandboxContext,
        issue_context: IssueContext,
    ) -> PatchResult:
        #  1. Read current file contents from sandbox 
        file_contents = self._read_files(ctx, issue_context)

        # 2. Generate diff via LLM 
        diff = await self._generate_diff(issue_context, file_contents)

        # 3. Validate 
        allowed_paths = {step.file_path for step in issue_context.plan_steps}
        self._validate_diff(diff, allowed_paths)

        # 4 & 5. Apply inside sandbox 
        patch_result = self._apply_diff(ctx, diff)

        logger.info(
            "patch_applicator.applied",
            run_id=ctx.run_id,
            files_changed=len(patch_result.files_changed),
            lines_added=patch_result.lines_added,
            lines_removed=patch_result.lines_removed,
        )
        return patch_result

    #  private 

    def _read_files(
        self, ctx: SandboxContext, issue_context: IssueContext
    ) -> dict[str, str]:
        contents: dict[str, str] = {}
        for step in issue_context.plan_steps:
            if step.action == "add":
                contents[step.file_path] = ""   # new file — no existing content
                continue
            result = self._manager.exec(
                ctx,
                ["cat", step.file_path],
                workdir=ctx.repo_dir,
            )
            if result.exit_code == 0:
                contents[step.file_path] = result.stdout
            else:
                logger.warning(
                    "patch_applicator.file_not_found",
                    path=step.file_path,
                    run_id=ctx.run_id,
                )
                contents[step.file_path] = ""
        return contents

    async def _generate_diff(
        self,
        issue_context: IssueContext,
        file_contents: dict[str, str],
    ) -> str:
        raw_messages = prompts.build_messages(
            repo_full_name=issue_context.repo_full_name,
            issue_number=issue_context.issue_number,
            issue_title=issue_context.issue_title,
            cleaned_description=issue_context.cleaned_description,
            acceptance_criteria=issue_context.acceptance_criteria,
            plan_steps=[s.model_dump() for s in issue_context.plan_steps],
            file_contents=file_contents,
        )
        messages = [LLMMessage(role=m["role"], content=m["content"]) for m in raw_messages]

        llm = get_llm_provider()
        # Use a slightly higher token budget for diffs
        response = await llm.complete(
            messages=messages,
            config=LLMConfig(max_tokens=8192),
        )

        diff = self._strip_markdown_fences(response.content.strip())
        if not diff:
            raise ValueError("LLM returned an empty diff")
        return diff

    def _validate_diff(self, diff: str, allowed_paths: set[str]) -> None:
        """Parse the diff header lines and enforce scope/safety rules."""
        changed_files: list[str] = []
        lines_added = 0
        lines_removed = 0

        for line in diff.splitlines():
            if line.startswith("+++ b/"):
                path = line[6:].strip()
                changed_files.append(path)
                # Path traversal check
                if ".." in path or path.startswith("/"):
                    raise ValueError(f"Unsafe path in diff: {path!r}")
                # Scope check
                if path not in allowed_paths:
                    raise ValueError(
                        f"Diff touches {path!r} which is not in the plan. "
                        f"Allowed: {allowed_paths}"
                    )
            elif line.startswith("+") and not line.startswith("+++"):
                lines_added += 1
            elif line.startswith("-") and not line.startswith("---"):
                lines_removed += 1

        if not changed_files:
            raise ValueError("Diff contains no file changes")
        if len(changed_files) > _MAX_FILES_CHANGED:
            raise ValueError(
                f"Diff touches {len(changed_files)} files, max is {_MAX_FILES_CHANGED}"
            )
        total_lines = lines_added + lines_removed
        if total_lines > _MAX_LINES_CHANGED:
            raise ValueError(
                f"Diff changes {total_lines} lines, max is {_MAX_LINES_CHANGED}"
            )

    def _apply_diff(self, ctx: SandboxContext, diff: str) -> PatchResult:
        """Write the diff to a temp file inside the sandbox and apply it."""
        patch_path = f"{ctx.workspace_path}/changes.patch"

        # Write patch file via echo — avoids needing a volume write from Python
        # Use a here-doc style: write line by line
        write_result = self._manager.exec(
            ctx,
            ["bash", "-c", f"cat > {patch_path}"],
            workdir=ctx.repo_dir,
        )
        # Actually write via tee since exec_run doesn't support stdin easily
        # Write to host workspace instead (it's mounted)
        host_patch = os.path.join(ctx.host_workspace, "changes.patch")
        with open(host_patch, "w") as f:
            f.write(diff)

        # Apply the patch
        apply_result = self._manager.exec(
            ctx,
            ["patch", "-p1", "--input", f"{ctx.workspace_path}/changes.patch"],
            workdir=ctx.repo_dir,
        )
        if apply_result.exit_code != 0:
            raise RuntimeError(
                f"patch -p1 failed (exit {apply_result.exit_code}):\n"
                f"{apply_result.stdout}\n{apply_result.stderr}"
            )

        # Parse stats from the applied diff
        files_changed, lines_added, lines_removed = self._parse_diff_stats(diff)

        return PatchResult(
            diff=diff,
            files_changed=files_changed,
            lines_added=lines_added,
            lines_removed=lines_removed,
        )

    @staticmethod
    def _parse_diff_stats(diff: str) -> tuple[list[str], int, int]:
        files_changed: list[str] = []
        lines_added = 0
        lines_removed = 0
        for line in diff.splitlines():
            if line.startswith("+++ b/"):
                files_changed.append(line[6:].strip())
            elif line.startswith("+") and not line.startswith("+++"):
                lines_added += 1
            elif line.startswith("-") and not line.startswith("---"):
                lines_removed += 1
        return files_changed, lines_added, lines_removed

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        """Remove ```diff ... ``` wrappers if the LLM added them."""
        text = re.sub(r"^```(?:diff)?\s*\n", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n```\s*$", "", text, flags=re.MULTILINE)
        return text.strip()