"""Provider name -> adapter factory (ADR-0063). Adding a provider is one adapter file plus one
``register`` line in ``_register_builtin``; factories import their adapter lazily so a missing
optional package (``yfinance``) only matters when that provider is chosen."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from crucible.core.errors import ConfigurationError

if TYPE_CHECKING:
    from crucible.data.providers.base import BarsProvider
    from crucible.data.providers.settings import ProviderSettings

ProviderFactory = Callable[..., "BarsProvider"]
"""``factory(settings, **kwargs) -> BarsProvider``; kwargs are calendar, feed latency, ..."""

_FACTORIES: dict[str, ProviderFactory] = {}


def register(name: str, factory: ProviderFactory) -> None:
    _FACTORIES[name] = factory


def unregister(name: str) -> None:
    _FACTORIES.pop(name, None)


def provider_names() -> list[str]:
    return sorted(_FACTORIES)


def build_provider(name: str, settings: ProviderSettings, **kwargs: object) -> BarsProvider:
    """The adapter called ``name``; ``kwargs`` (calendar, feed latency, transport, ...) go to it."""
    factory = _FACTORIES.get(name)
    if factory is None:
        msg = (
            f"unknown data provider {name!r}; available: "
            f"{', '.join(provider_names()) or '(none registered)'}"
        )
        raise ConfigurationError(msg)
    return factory(settings, **kwargs)


def _tiingo(settings: ProviderSettings, **kwargs: object) -> BarsProvider:
    from crucible.data.providers.tiingo import build

    return build(settings, **kwargs)


register("tiingo", _tiingo)


def _yfinance(settings: ProviderSettings, **kwargs: object) -> BarsProvider:
    from crucible.data.providers.yfinance import build

    return build(settings, **kwargs)


register("yfinance", _yfinance)
