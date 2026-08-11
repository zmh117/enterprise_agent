from .admin_controller import build_identity_admin_router
from .auth_controller import build_auth_router
from .external_identity_controller import build_external_identity_router

__all__ = [
    "build_auth_router",
    "build_external_identity_router",
    "build_identity_admin_router",
]
