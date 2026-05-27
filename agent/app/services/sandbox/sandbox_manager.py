import contextlib
import os
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator

import docker
import docker.errors
from docker.models.containers import Container

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_seconds: float = 0.0


@dataclass
class SandboxContext:
    container: Container
    run_id: str
    workspace_path: str          # path INSIDE the container
    host_workspace: str          # tmpdir on the host (mounted into container)
    repo_dir: str                # workspace_path/repo inside container


class SandboxManager:
    """Manages the lifecycle of an ephemeral Docker sandbox.

    Usage:
        async with SandboxManager().create(run_id, repo_url) as ctx:
            result = ctx.exec(["pytest", "-x"])

    The container is guaranteed to be removed on exit, even on exception.
    Network is fully disabled inside the container (--network=none).
    The repo is cloned on the HOST before the container starts so we don't
    need network access inside the sandbox.
    """

    # Non-root user inside the container
    _CONTAINER_USER = "nobody"
    _WORKSPACE = "/workspace"

    def __init__(self) -> None:
        self._client = docker.from_env()

    @contextlib.contextmanager
    def create(self, run_id: str, repo_url: str) -> Generator[SandboxContext, None, None]:
        host_workspace = tempfile.mkdtemp(prefix=f"agent-{run_id}-")
        container: Container | None = None

        try:
            # Clone repo on host (needs network, before container starts) 
            repo_dir_host = os.path.join(host_workspace, "repo")
            self._clone_repo(repo_url, repo_dir_host)

            # Spawn container 
            container = self._spawn(run_id, host_workspace)
            logger.info("sandbox.created", run_id=run_id, container_id=container.short_id)

            ctx = SandboxContext(
                container=container,
                run_id=run_id,
                workspace_path=self._WORKSPACE,
                host_workspace=host_workspace,
                repo_dir=f"{self._WORKSPACE}/repo",
            )
            yield ctx

        finally:
            self._teardown(container, host_workspace, run_id)

    # private 

    def _clone_repo(self, repo_url: str, dest: str) -> None:
        """Shallow clone into a temp directory on the host."""
        logger.info("sandbox.cloning", repo_url=repo_url)
        result = subprocess.run(
            ["git", "clone", "--depth=1", repo_url, dest],
            capture_output=True,
            text=True,
            timeout=settings.sandbox_clone_timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git clone failed (exit {result.returncode}): {result.stderr}"
            )
        logger.info("sandbox.clone_complete", dest=dest)

    def _spawn(self, run_id: str, host_workspace: str) -> Container:
        """Start an isolated Docker container with the workspace mounted."""
        mem_bytes = self._parse_memory(settings.sandbox_memory_limit)
        cpu_period = 100_000
        cpu_quota = int(cpu_period * settings.sandbox_cpu_quota)

        container = self._client.containers.run(
            image=settings.sandbox_image,
            command="sleep infinity",   # keep alive; we exec commands into it
            detach=True,
            remove=False,              # we remove manually in teardown
            network_disabled=True,     # --network=none equivalent
            read_only=False,           # repo needs to be writable
            user=self._CONTAINER_USER,
            working_dir=self._WORKSPACE,
            mem_limit=mem_bytes,
            cpu_period=cpu_period,
            cpu_quota=cpu_quota,
            volumes={
                host_workspace: {
                    "bind": self._WORKSPACE,
                    "mode": "rw",
                }
            },
            environment={
                "HOME": "/tmp",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            labels={"agent.run_id": run_id},
            name=f"agent-sandbox-{run_id[:8]}",
        )
        return container

    def exec(
        self,
        ctx: SandboxContext,
        cmd: list[str],
        workdir: str | None = None,
        timeout: int | None = None,
    ) -> ExecResult:
        """Run a command inside the container and return its output.

        Enforces a hard timeout — kills the exec if it exceeds it.
        """
        effective_timeout = timeout or settings.sandbox_exec_timeout
        effective_workdir = workdir or ctx.repo_dir
        start = time.monotonic()
        timed_out = False

        try:
            exit_code, output = ctx.container.exec_run(
                cmd=cmd,
                workdir=effective_workdir,
                user=self._CONTAINER_USER,
                demux=True,
                tty=False,
                timeout=effective_timeout,
            )
            stdout_bytes, stderr_bytes = output if output else (b"", b"")
            stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
            stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")

        except Exception as exc:
            if "timeout" in str(exc).lower():
                timed_out = True
                exit_code = -1
                stdout = ""
                stderr = f"Command timed out after {effective_timeout}s: {exc}"
            else:
                raise

        duration = time.monotonic() - start
        logger.info(
            "sandbox.exec",
            run_id=ctx.run_id,
            cmd=" ".join(str(c) for c in cmd),
            exit_code=exit_code,
            duration=round(duration, 2),
            timed_out=timed_out,
        )
        return ExecResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            duration_seconds=round(duration, 2),
        )

    def _teardown(
        self,
        container: Container | None,
        host_workspace: str,
        run_id: str,
    ) -> None:
        if container:
            try:
                container.stop(timeout=5)
                container.remove(force=True)
                logger.info("sandbox.removed", run_id=run_id)
            except docker.errors.NotFound:
                pass
            except Exception as exc:
                logger.warning("sandbox.remove_failed", run_id=run_id, error=str(exc))

        # Clean up host tmpdir
        import shutil
        try:
            shutil.rmtree(host_workspace, ignore_errors=True)
        except Exception as exc:
            logger.warning("sandbox.cleanup_failed", path=host_workspace, error=str(exc))

    @staticmethod
    def _parse_memory(limit: str) -> int:
        """Convert '512m' / '2g' to bytes."""
        limit = limit.lower().strip()
        if limit.endswith("g"):
            return int(limit[:-1]) * 1024 ** 3
        if limit.endswith("m"):
            return int(limit[:-1]) * 1024 ** 2
        if limit.endswith("k"):
            return int(limit[:-1]) * 1024
        return int(limit)