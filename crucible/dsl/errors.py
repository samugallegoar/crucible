"""The one error the expression DSL raises: :class:`ExpressionError` (ADR-0096).

Every refusal carries the 1-based column, the offending token and a hint, so the message says
what was wrong, where it was, and how to fix it (AGENTS.md §5, ``docs/CONVENTIONS.md`` §9).
"""

from __future__ import annotations

from crucible.core.errors import ConfigurationError


class ExpressionError(ConfigurationError):
    """An expression could not be tokenized, parsed, typed or canonicalized.

    ``column`` is the 1-based character offset of the offending token (``None`` when the refusal
    concerns the whole text, e.g. an empty expression); ``token`` is the offending token text;
    ``hint`` repeats the actionable part of the message for programmatic callers.
    """

    def __init__(
        self,
        message: str,
        *,
        column: int | None = None,
        token: str | None = None,
        hint: str | None = None,
    ) -> None:
        parts = [message]
        if token is not None:
            parts.append(f"at {token!r}")
        if column is not None:
            parts.append(f"(column {column})")
        if hint:
            parts.append(f"hint: {hint}")
        self.column = column
        self.token = token
        self.hint = hint
        super().__init__(" ".join(parts))
        if column is not None:
            self.at(column=column)
        if token is not None:
            self.at(token=token)

    @classmethod
    def at_token(
        cls,
        message: str,
        *,
        column: int,
        token: str,
        hint: str | None = None,
    ) -> ExpressionError:
        """Convenience builder for a refusal at a token."""
        return cls(message, column=column, token=token, hint=hint)
