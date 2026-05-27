import os
import time
from typing import NamedTuple

import yaml

from app.config import settings
from app.core.logging import get_logger
from app.schemas.sandbox import CIPhaseResult, CIResult
from app.services.sandbox.sandbox_manager import SandboxContext, SandboxManager

logger = get_logger(__name__)


class CICommands(NamedTuple):
    lint: str | None
    test: str | None
    build: str | None


_AGENT_YAML = "agent.yaml"

# Auto-detection fallback — ordered by preference
_LINT_CANDIDATES = [
    "ruff check .",
    "flake8 .",
    "pylint .",
    "eslint .",
    "npx eslint .",
]
_TEST_CANDIDATES = [
    "pytest",
    "python -m pytest",
    "npm test",
    "yarn test",
    "go test ./...",
]
_BUILD_CANDIDATES = [
    "python -m py_compile $(find . -name '*.py' | head -20)",
    "npm run build",
    "yarn build",
    "go build ./...",
    "cargo build",
]


class CIRunner:
    """Runs lint → test → build inside the sandbox.

    Command resolution order:
      1. agent.yaml in repo root (authoritative)
      2. Auto-detection from pyproject.toml / package.json / Makefile
      3. Hardcoded fallback candidates (tried in order, first exit-0 wins)

    A phase with no detected command is skipped (not failed).
    """

    def __init__(self, manager: SandboxManager) -> None:
        self._manager = manager

    def run(self, ctx: SandboxContext) -> CIResult:
        commands = self._resolve_commands(ctx)
        logger.info(
            "ci_runner.commands",
            run_id=ctx.run_id,
            lint=commands.lint,
            test=commands.test,
            build=commands.build,
        )

        phases: list[CIPhaseResult] = []

        for phase_name, cmd, timeout in [
            ("lint",  commands.lint,  settings.ci_timeout_lint),
            ("test",  commands.test,  settings.ci_timeout_test),
            ("build", commands.build, settings.ci_timeout_build),
        ]:
            if not cmd:
                logger.info("ci_runner.phase_skipped", phase=phase_name, run_id=ctx.run_id)
                continue

            phase_result = self._run_phase(ctx, phase_name, cmd, timeout)
            phases.append(phase_result)

            if not phase_result.passed:
                logger.warning(
                    "ci_runner.phase_failed",
                    phase=phase_name,
                    exit_code=phase_result.exit_code,
                    run_id=ctx.run_id,
                )
                # Stop on first failure — no point running tests if lint hard-fails
                break

        all_passed = all(p.passed for p in phases)
        return CIResult(passed=all_passed, phases=phases)

    # private 

    def _run_phase(
        self, ctx: SandboxContext, phase: str, cmd: str, timeout: int
    ) -> CIPhaseResult:
        start = time.monotonic()
        logger.info("ci_runner.phase_start", phase=phase, cmd=cmd, run_id=ctx.run_id)

        result = self._manager.exec(
            ctx,
            ["bash", "-c", cmd],
            workdir=ctx.repo_dir,
            timeout=timeout,
        )
        duration = time.monotonic() - start

        return CIPhaseResult(
            phase=phase,
            passed=result.exit_code == 0 and not result.timed_out,
            exit_code=result.exit_code,
            stdout=result.stdout[-10_000:],   # cap at 10k chars
            stderr=result.stderr[-5_000:],
            duration_seconds=round(duration, 2),
            timed_out=result.timed_out,
        )

    def _resolve_commands(self, ctx: SandboxContext) -> CICommands:
        # Try agent.yaml first
        agent_yaml = self._read_agent_yaml(ctx)
        if agent_yaml:
            return CICommands(
                lint=agent_yaml.get("lint"),
                test=agent_yaml.get("test"),
                build=agent_yaml.get("build"),
            )

        # Auto-detect from repo metadata
        return self._auto_detect(ctx)

    def _read_agent_yaml(self, ctx: SandboxContext) -> dict | None:
        result = self._manager.exec(
            ctx,
            ["cat", _AGENT_YAML],
            workdir=ctx.repo_dir,
        )
        if result.exit_code != 0:
            return None
        try:
            data = yaml.safe_load(result.stdout)
            if isinstance(data, dict) and ("test" in data or "lint" in data):
                logger.info("ci_runner.using_agent_yaml", run_id=ctx.run_id)
                return data
        except yaml.YAMLError:
            pass
        return None

    def _auto_detect(self, ctx: SandboxContext) -> CICommands:
        logger.info("ci_runner.auto_detecting", run_id=ctx.run_id)

        # Check which files exist to narrow candidates
        has_pyproject = self._file_exists(ctx, "pyproject.toml")
        has_package_json = self._file_exists(ctx, "package.json")
        has_makefile = self._file_exists(ctx, "Makefile")

        lint = self._detect_command(ctx, _LINT_CANDIDATES, prefer_python=has_pyproject)
        test = self._detect_command(ctx, _TEST_CANDIDATES, prefer_python=has_pyproject)
        build = self._detect_command(ctx, _BUILD_CANDIDATES, prefer_python=has_pyproject)

        logger.info(
            "ci_runner.auto_detect_result",
            run_id=ctx.run_id,
            lint=lint,
            test=test,
            build=build,
        )
        return CICommands(lint=lint, test=test, build=build)

    def _detect_command(
        self,
        ctx: SandboxContext,
        candidates: list[str],
        prefer_python: bool = False,
    ) -> str | None:
        """Try each candidate by checking if the binary exists; return the first viable one."""
        ordered = candidates
        if prefer_python:
            # Put Python-first candidates at the top
            py = [c for c in candidates if "pytest" in c or "ruff" in c or "python" in c or "py_compile" in c]
            rest = [c for c in candidates if c not in py]
            ordered = py + rest

        for cmd in ordered:
            binary = cmd.split()[0]
            check = self._manager.exec(ctx, ["which", binary], workdir=ctx.repo_dir)
            if check.exit_code == 0:
                return cmd
        return None

    def _file_exists(self, ctx: SandboxContext, filename: str) -> bool:
        result = self._manager.exec(
            ctx,
            ["test", "-f", filename],
            workdir=ctx.repo_dir,
        )
        return result.exit_code == 0