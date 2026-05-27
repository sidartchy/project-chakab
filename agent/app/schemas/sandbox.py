from pydantic import BaseModel, Field


class PatchResult(BaseModel):
    """Output of the patch applicator."""
    diff: str = Field(description="Unified diff string that was applied")
    files_changed: list[str] = Field(description="List of file paths that were modified")
    lines_added: int = 0
    lines_removed: int = 0


class CIPhaseResult(BaseModel):
    """Result of a single CI phase (lint, test, or build)."""
    phase: str                    # "lint" | "test" | "build"
    passed: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False


class CIResult(BaseModel):
    """Aggregated result of all CI phases."""
    passed: bool
    phases: list[CIPhaseResult]
    log_url: str = ""             # S3 or local path where full logs are stored

    @property
    def failed_phase(self) -> CIPhaseResult | None:
        return next((p for p in self.phases if not p.passed), None)

    @property
    def combined_logs(self) -> str:
        parts = []
        for p in self.phases:
            parts.append(f"=== {p.phase.upper()} (exit {p.exit_code}) ===")
            if p.stdout:
                parts.append(p.stdout)
            if p.stderr:
                parts.append(p.stderr)
        return "\n".join(parts)


class SandboxResult(BaseModel):
    """Full result of one sandbox execution attempt."""
    passed: bool
    patch: PatchResult | None = None
    ci: CIResult | None = None
    failure_reason: str = ""
    retry_count: int = 0