import time
from typing import Any

import jwt
import pydantic
from fastapi import APIRouter
from pydantic import BaseModel

from app.config import Settings

router = APIRouter(tags=["dev-auth"])

class Persona(BaseModel):
    """Request body for dev token minting — camelCase from the frontend."""

    model_config = {"populate_by_name": True}

    id: str
    label: str
    role: str
    clearance: int
    tenant_id: str = pydantic.Field(alias="tenantId")
    department_id: str = pydantic.Field(alias="departmentId")

@router.post("/dev/token")
def mint_dev_token(persona: Persona) -> dict[str, str]:
    settings = Settings()
    if settings.env != "dev":
        raise RuntimeError("Token minting is only allowed in dev environment")

    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": f"dev-{persona.id}",
        "tenant_id": persona.tenant_id,
        "department_id": persona.department_id,
        "role": persona.role,
        "clearance_rank": persona.clearance,
        "iat": now,
        "exp": now + 86400 * 7,
        "aud": "docmgmt-api",
    }

    token = jwt.encode(payload, settings.dev_jwt_secret, algorithm="HS256")
    return {"access_token": token}
