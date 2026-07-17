from .admin_controller import build_identity_admin_router
from .auth_controller import build_auth_router

__all__ = ["build_auth_router", "build_identity_admin_router"]
