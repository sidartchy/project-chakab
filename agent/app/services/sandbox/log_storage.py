import os
from pathlib import Path

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class LogStorage:
    """Stores CI logs either locally or in S3 depending on config.

    Returns the URL/path where the log was stored.
    """

    async def save(self, run_id: str, phase: str, content: str) -> str:
        if settings.log_storage_backend == "s3":
            return await self._save_s3(run_id, phase, content)
        return await self._save_local(run_id, phase, content)

    async def _save_local(self, run_id: str, phase: str, content: str) -> str:
        log_dir = Path(settings.local_log_dir) / run_id
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{phase}.log"
        log_path.write_text(content, encoding="utf-8")
        logger.info("log_storage.saved_local", path=str(log_path))
        return str(log_path)

    async def _save_s3(self, run_id: str, phase: str, content: str) -> str:
        try:
            import boto3
            key = f"{settings.s3_prefix}/{run_id}/{phase}.log"
            s3 = boto3.client("s3", region_name=settings.aws_region)
            s3.put_object(
                Bucket=settings.s3_bucket,
                Key=key,
                Body=content.encode("utf-8"),
                ContentType="text/plain",
            )
            url = f"s3://{settings.s3_bucket}/{key}"
            logger.info("log_storage.saved_s3", url=url)
            return url
        except Exception as exc:
            logger.warning("log_storage.s3_failed", error=str(exc))
            # Fallback to local on S3 failure
            return await self._save_local(run_id, phase, content)