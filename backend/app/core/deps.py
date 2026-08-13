"""Current-user resolution (Feature 1: User Identity & Data Foundation).

NON-PRODUCTION STAND-IN. There is no real authentication provider wired up
yet — per docs/constraints.md, adopting a specific auth provider is a
sign-off item. Until then, this dependency resolves "the current user" from
a plain header and find-or-creates a matching `User` row, purely so later
routes (Feature 4+) have something to attribute a ResearchRun to during
local development.

This must never run with `environment=production` (see the guard below) —
it is not a substitute for real auth.
"""

import logging

from fastapi import Depends, Header, HTTPException
from prisma.models import User

from app.core.config import Settings, get_settings
from app.db.prisma_client import prisma

logger = logging.getLogger(__name__)

_DEV_DEFAULT_EMAIL = "dev@local.test"


async def get_current_user(
    x_dev_user_email: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> User:
    if settings.is_production:
        # This stand-in is dev-only; a real auth provider must replace it
        # before this can ever run in production (docs/constraints.md).
        raise HTTPException(
            status_code=500,
            detail="No authentication provider configured for production.",
        )

    email = x_dev_user_email or _DEV_DEFAULT_EMAIL

    user = await prisma.user.find_unique(where={"email": email})
    if user is None:
        user = await prisma.user.create(data={"email": email})
        logger.info("dev current-user stand-in created a new user record")

    return user
