from fastapi import APIRouter

from ..config import get_settings

router = APIRouter(prefix="/api")


@router.get("/config")
def get_client_config() -> dict:
    """Subset of the backend's config that the frontend needs at runtime.

    `homePath` is the deployment's sub-path prefix (e.g. `/wiki`, or `''`
    when mounted at root). The frontend uses it ONLY as React Router's
    basename so internal pushState navigation lands at the right URL — it
    deliberately doesn't prefix outgoing API/WS/asset URLs (the reverse
    proxy strips the prefix on its end before forwarding to us).
    """
    s = get_settings()
    return {
        "gracePeriodSeconds": s.grace_period_seconds,
        "homePath": s.base_url,
    }
