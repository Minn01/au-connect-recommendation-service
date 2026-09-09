from fastapi import HTTPException, Header
import secrets

from au_connect_recommendation_service.core.env import INTERNAL_API_KEY


async def verifyServiceKey(x_internal_service_key: str | None = Header(default=None)):
    if not x_internal_service_key:
        raise HTTPException(status_code=401, detail="Missing internal key")

    if not secrets.compare_digest(x_internal_service_key, INTERNAL_API_KEY):
        raise HTTPException(status_code=403, detail="Invalid service key")
