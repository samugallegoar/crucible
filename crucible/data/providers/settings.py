"""API keys and provider selection from the environment and a ``.env`` file (ADR-0063).

The real environment wins over ``.env``; nothing here modifies ``os.environ``. A key lives in
:class:`ApiKey`, whose ``repr``/``str`` are masked, so it cannot reach a log line, an exception
message, a manifest or a report by accident. A malformed ``.env`` line is refused by line number
only, never by content, because the content may be a secret.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from crucible.core.errors import ConfigurationError
from crucible.data.providers.errors import MissingApiKeyError

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_PROVIDER = "yfinance"
PROVIDER_ENV = "CRUCIBLE_DATA_PROVIDER"
DOTENV_NAME = ".env"

_KEY_HELP: dict[str, str] = {
    "tiingo": (
        "Tiingo needs a free API key: create an account at https://www.tiingo.com, copy the API "
        "token from your account page, then put {env}=<your token> in a .env file in the folder "
        "you run crucible from (copy .env.example to .env), or set {env} in your shell"
    ),
}


class ApiKey:
    """A secret. ``reveal()`` is the only way to read it."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "ApiKey(****)"

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return "ApiKey(****)"

    def __reduce__(self) -> tuple[type[ApiKey], tuple[str]]:
        # pickling would copy the secret to disk or another process: refuse
        msg = "an ApiKey cannot be pickled"
        raise TypeError(msg)


def parse_dotenv(path: Path) -> dict[str, str]:
    """``KEY=VALUE`` lines; ``#`` comments, ``export `` prefix and single or double quotes allowed.
    A missing file is an empty mapping; an invalid line is a ``ConfigurationError`` naming the file
    and line number (never its content)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"cannot read {path} as UTF-8 text: {type(exc).__name__}"
        raise ConfigurationError(msg) from None
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not name or not name.replace("_", "").isalnum():
            msg = (
                f"{path} line {number} is not KEY=VALUE "
                "(the content is not shown: it may be a secret)"
            )
            raise ConfigurationError(msg)
        value = value.strip()
        closing = value.find(value[:1], 1) if value[:1] in {'"', "'"} else -1
        if closing != -1:
            value = value[1:closing]
        else:
            hash_at = value.find(" #")
            if hash_at != -1:
                value = value[:hash_at].rstrip()
        values[name] = value
    return values


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    """The merged view of ``.env`` and the environment (the environment wins)."""

    _values: dict[str, str] = field(repr=False, compare=False)

    @classmethod
    def load(
        cls, *, environ: Mapping[str, str] | None = None, dotenv_path: Path | None = None
    ) -> ProviderSettings:
        merged = parse_dotenv(dotenv_path if dotenv_path is not None else Path(DOTENV_NAME))
        merged.update(os.environ if environ is None else environ)
        return cls(merged)

    def __repr__(self) -> str:
        return f"ProviderSettings({len(self._values)} variables, values hidden)"

    __str__ = __repr__

    def __reduce__(self) -> tuple[type[ProviderSettings], tuple[dict[str, str]]]:
        # the values include API keys: pickling would copy them to disk or another process
        msg = "ProviderSettings cannot be pickled (it holds API keys)"
        raise TypeError(msg)

    def default_provider(self) -> str:
        return self._values.get(PROVIDER_ENV, "").strip() or DEFAULT_PROVIDER

    def api_key(self, env_name: str, *, provider: str) -> ApiKey:
        value = self._values.get(env_name, "").strip()
        if not value:
            help_text = _KEY_HELP.get(provider, "set {env} to your {provider} API key").format(
                env=env_name, provider=provider
            )
            msg = f"{env_name} is not set. {help_text}. See .env.example for every variable"
            raise MissingApiKeyError(msg)
        return ApiKey(value)
