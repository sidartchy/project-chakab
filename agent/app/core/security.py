import hashlib
import hmac

from fastapi import HTTPException, Request, status

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def verify_github_signature(request: Request) -> bytes:
    """Validate GitHub's X-Hub-Signature-256 header.

    Returns the raw body so the route handler doesn't need to re-read it.
    Raises HTTP 401 if the signature is missing or invalid.
    """
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        logger.warning("webhook.missing_signature", headers=dict(request.headers))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Hub-Signature-256 header",
        )

    body = await request.body()

    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature_header):
        logger.warning("webhook.invalid_signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    return body