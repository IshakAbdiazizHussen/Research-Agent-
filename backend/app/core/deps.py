"""Current-user resolution (Feature 1: User Identity & Data Foundation).

Two paths, branched on `settings.is_production`:

- **Development:** unchanged dev stand-in — resolves "the current user"
  from a plain client-supplied `X-Dev-User-Email` header and find-or-
  creates a matching `User` row. Not a substitute for real auth.
- **Production (Tier 1 fix — see docs/architecture.md decision log
  "Production auth: shared-secret gate + fixed identity"):** originally
  this hard-failed every request (`raise HTTPException(500, ...)`), which
  a post-launch audit found meant `POST /research` and
  `GET /research/{id}/stream` had never actually worked in production —
  only `/health` did. Replaced with a shared-secret gate
  (`X-App-Secret`, checked via `settings.app_shared_secret`) plus
  resolution to a single fixed account (`settings.production_user_email`).
  Client-supplied identity is never trusted in production — the secret
  proves "this request came from someone holding it" (itself necessarily
  public, baked into the Vercel frontend's JS bundle), not who that person
  is; the fixed identity is what actually removes the impersonation risk,
  since there is no longer any client input that selects *which* user a
  request acts as. This is still not real per-customer auth — correct only
  because this is a portfolio-stage, single-real-user deployment; a real
  auth provider is the sign-off-worthy next step once a second real
  customer needs isolated data (docs/constraints.md).
"""

import logging
import secrets

from fastapi import Depends, Header, HTTPException
from prisma.models import User

from app.core.config import Settings, get_settings
from app.db.prisma_client import prisma

logger = logging.getLogger(__name__)

_DEV_DEFAULT_EMAIL = "dev@local.test"


def _secret_matches(provided: str | None, expected: str | None) -> bool:
    """Constant-time comparison — a shared secret checked with `==` leaks
    timing information about how many leading characters matched."""
    if not provided or not expected:
        return False
    return secrets.compare_digest(provided, expected)


async def get_current_user(
    x_dev_user_email: str | None = Header(default=None),
    x_app_secret: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> User:
    if settings.is_production:
        if not _secret_matches(x_app_secret, settings.app_shared_secret):
            # Generic 401, no detail on *why* — don't tell a caller whether
            # the header was missing vs. wrong (docs/development_plan.md
            # Security: no internal detail in customer-visible errors).
            raise HTTPException(status_code=401, detail="Unauthorized.")

        email = settings.production_user_email
        if not email:
            # Belt-and-suspenders: app/main.py's startup validation should
            # already have refused to boot without this set in production.
            logger.error("production_user_email is unset despite is_production=True")
            raise HTTPException(status_code=500, detail="Server misconfigured.")
    else:
        email = x_dev_user_email or _DEV_DEFAULT_EMAIL

    user = await prisma.user.find_unique(where={"email": email})
    if user is None:
        user = await prisma.user.create(data={"email": email})
        logger.info("current-user resolution created a new user record")

    return user
