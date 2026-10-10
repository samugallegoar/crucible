"""Errors raised by data providers (ADR-0063). Every message says what failed, for which
provider and symbol, and how to fix it; none ever contains an API key."""

from __future__ import annotations

from crucible.core.errors import ConfigurationError, CrucibleError


class ProviderError(CrucibleError):
    """A provider could not supply the requested data."""


class MissingApiKeyError(ConfigurationError):
    """A provider needs an API key that is not set."""


class ProviderUnavailableError(ConfigurationError):
    """A provider's optional package is not installed."""


class ProviderAuthError(ProviderError):
    """The provider rejected the credentials (HTTP 401/403)."""


class ProviderRateLimitError(ProviderError):
    """The provider's rate limit was hit and retries were exhausted."""


class ProviderNetworkError(ProviderError):
    """The provider could not be reached (or answered with a server error) after the retries."""


class UnknownSymbolError(ProviderError):
    """The provider has no data for the symbol (HTTP 404 or an unknown ticker)."""


class EmptyDataError(ProviderError):
    """The provider answered, but with no rows for the requested range."""
