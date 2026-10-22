from fastapi import APIRouter, Depends

from .. import settings
from ..models import User
from ..security import current_user

router = APIRouter(prefix="/api/themes", tags=["themes"])


@router.get("/rules")
def rules(user: User = Depends(current_user)):
    """Admin-defined tag → skin rules (they win over the built-in ones)."""
    return {"genre_skins": settings.get("genre_skins"), "skin_map": settings.get("skin_map") or {},
            "default_scheme": settings.get("default_scheme"), "default_mode": settings.get("default_mode")}
