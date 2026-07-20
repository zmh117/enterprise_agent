"""Webhook public and administration API adapters."""
from .admin_controller import build_webhook_admin_router
from .public_controller import build_public_webhook_router

__all__ = ["build_public_webhook_router", "build_webhook_admin_router"]
