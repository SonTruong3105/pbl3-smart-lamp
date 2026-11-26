"""Provider registry package.

Provider implementations are imported explicitly by runtime/connection setup so
missing optional providers do not prevent the application from starting.
"""

from app.core.providers.base import ProviderRegistry

__all__ = ["ProviderRegistry"]
