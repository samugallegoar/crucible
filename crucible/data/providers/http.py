"""HTTP GET with bounded retry and typed errors, over stdlib ``urllib`` (ADR-0063).

``get_with_retry`` takes the transport and ``sleep`` as arguments so it is tested without a
network or a clock. Credentials travel in headers only and are never put in a URL or an error
message. Retry/backoff is I/O-boundary code: nothing in a simulation reads the clock.
"""

from __future__ import annotations

import http.client
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from crucible.data.providers.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderNetworkError,
    ProviderRateLimitError,
    UnknownSymbolError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib copies every header (the API key) to a redirect target, even another host or plain
    http; a redirect is returned as an ordinary 3xx response instead and refused by the caller."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


# A transport is ``transport(url, headers) -> HttpResponse``: it returns error statuses as
# responses and raises an ``OSError`` only when the server could not be reached at all.
def urllib_transport(*, timeout: float = 30.0) -> Callable[[str, Mapping[str, str]], HttpResponse]:
    def get(url: str, headers: Mapping[str, str]) -> HttpResponse:
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
        try:
            with _OPENER.open(request, timeout=timeout) as response:
                return HttpResponse(
                    response.status,
                    dict(response.headers.items()),
                    response.read(),
                )
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, dict(exc.headers.items()), exc.read())

    return get


def _retry_after(response: HttpResponse) -> float | None:
    for name, value in response.headers.items():
        if name.lower() == "retry-after":
            try:
                return max(0.0, float(value))
            except ValueError:
                return None
    return None


def get_with_retry(
    transport: Callable[[str, Mapping[str, str]], HttpResponse],
    url: str,
    headers: Mapping[str, str],
    *,
    provider: str,
    symbol: str,
    policy: RetryPolicy = RetryPolicy(),  # noqa: B008 - frozen dataclass, safe as a default
    sleep: Callable[[float], None] = time.sleep,
) -> HttpResponse:
    """The response of a successful GET, or a typed ``ProviderError``. 401/403 and 404 and other
    4xx are final; 429, 5xx and network errors are retried with exponential backoff (capped), a
    ``Retry-After`` shorter than the cap being honoured and a longer one failing at once with the
    wait time."""
    who = f"{provider} ({symbol})"
    last_problem = ""
    rate_limited = False
    for attempt in range(1, policy.max_attempts + 1):
        try:
            response = transport(url, headers)
        except (OSError, http.client.HTTPException) as exc:
            rate_limited = False
            last_problem = f"could not connect ({type(exc).__name__})"
        else:
            status = response.status
            if 200 <= status < 300:
                return response
            if status in {401, 403}:
                msg = (
                    f"{who}: the provider rejected the credentials (HTTP {status}); check that "
                    "the API key is correct, active and allowed to use this endpoint"
                )
                raise ProviderAuthError(msg)
            if status == 404:
                msg = (
                    f"{who}: the provider has no data for this symbol (HTTP 404); check the "
                    "ticker spelling and that the provider covers it"
                )
                raise UnknownSymbolError(msg)
            if status == 429:
                rate_limited = True
                wait = _retry_after(response)
                if wait is not None and wait > policy.max_delay_s:
                    msg = (
                        f"{who}: rate limit hit (HTTP 429); the provider asks to wait "
                        f"{wait:.0f} s, longer than the {policy.max_delay_s:.0f} s this tool "
                        "retries for. Wait and run the fetch again (cached symbols are kept)"
                    )
                    raise ProviderRateLimitError(msg)
                last_problem = "rate limit hit (HTTP 429)"
                if attempt < policy.max_attempts:
                    sleep(wait if wait is not None else backoff_delay(policy, attempt))
                continue
            if status >= 500:
                rate_limited = False
                last_problem = f"server error (HTTP {status})"
            else:
                msg = f"{who}: the provider refused the request (HTTP {status})"
                raise ProviderError(msg)
        if attempt < policy.max_attempts:
            sleep(backoff_delay(policy, attempt))
    if rate_limited:
        msg = (
            f"{who}: {last_problem} on all {policy.max_attempts} attempts; the free tier's rate "
            "limit is exhausted. Wait and run the fetch again (cached symbols are kept), or "
            "fetch fewer symbols at a time"
        )
        raise ProviderRateLimitError(msg)
    msg = (
        f"{who}: {last_problem} after {policy.max_attempts} attempts; check your internet "
        "connection and the provider's status page, then run the fetch again"
    )
    raise ProviderNetworkError(msg)


def backoff_delay(policy: RetryPolicy, attempt: int) -> float:
    return float(min(policy.max_delay_s, policy.base_delay_s * 2 ** (attempt - 1)))
