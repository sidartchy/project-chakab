from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

# Convenience type alias used in route signatures:
#   async def my_route(db: DbSession) -> ...
DbSession = Annotated[AsyncSession, Depends(get_db)]