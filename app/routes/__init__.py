"""
app/routes package initialization.
"""

from app.routes.check import router as check_router
from app.routes.resolve import router as resolve_router
from app.routes.ws import router as ws_router

__all__ = ["resolve_router", "check_router", "ws_router"]
