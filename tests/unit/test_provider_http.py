"""HTTP retry, error mapping and the urllib transport (ADR-0063).

No real network: the retry logic takes an injected transport and ``sleep``; the transport itself
is tested against a loopback server.
"""

from __future__ import annotations

import http.client
import http.server
import threading
from collections.abc import Iterator, Mapping
from typing import ClassVar

import pytest

from crucible.data.providers.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderNetworkError,
    ProviderRateLimitError,
    UnknownSymbolError,
)
from crucible.data.providers.http import (
    HttpResponse,
    RetryPolicy,
    get_with_retry,
    urllib_transport,
)

SECRET = "tk_live_0123456789abcdef"
URL = "https://example.invalid/prices?symbol=AAPL"
HEADERS = {"Authorization": f"Token {SECRET}"}


class _Script:
    """A transport that plays back a list of responses or exceptions and records the calls."""

    def __init__(self, *steps: HttpResponse | Exception) -> None:
        self._steps = list(steps)
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> HttpResponse:
        self.calls.append((url, headers))
        step = self._steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _ok(body: bytes = b"[]") -> HttpResponse:
    return HttpResponse(200, {}, body)


def _status(code: int, **headers: str) -> HttpResponse:
    return HttpResponse(code, headers, b"")


def _run(script: _Script, sleeps: list[float], policy: RetryPolicy | None = None) -> HttpResponse:
    return get_with_retry(
        script,
        URL,
        HEADERS,
        provider="tiingo",
        symbol="AAPL",
        policy=policy or RetryPolicy(max_attempts=4, base_delay_s=1.0, max_delay_s=30.0),
        sleep=sleeps.append,
    )


def test_a_success_is_returned_without_sleeping() -> None:
    script, sleeps = _Script(_ok(b"x")), []
    assert _run(script, sleeps).body == b"x"
    assert sleeps == []
    assert script.calls == [(URL, HEADERS)]


def test_server_errors_are_retried_with_exponential_backoff() -> None:
    script, sleeps = _Script(_status(500), _status(503), _ok()), []
    assert _run(script, sleeps).status == 200
    assert sleeps == [1.0, 2.0]


def test_network_errors_are_retried_then_reported() -> None:
    script, sleeps = _Script(*[OSError("boom")] * 4), []
    with pytest.raises(ProviderNetworkError, match=r"tiingo.*AAPL.*4 attempts"):
        _run(script, sleeps)
    assert sleeps == [1.0, 2.0, 4.0]
    assert len(script.calls) == 4


def test_a_server_error_that_never_clears_is_a_network_error() -> None:
    script = _Script(*[_status(502)] * 4)
    with pytest.raises(ProviderNetworkError, match="502"):
        _run(script, [])


def test_rate_limit_honours_a_short_retry_after() -> None:
    script, sleeps = _Script(_status(429, **{"Retry-After": "2"}), _ok()), []
    assert _run(script, sleeps).status == 200
    assert sleeps == [2.0]


def test_a_retry_after_longer_than_the_cap_fails_at_once_and_says_how_long() -> None:
    script, sleeps = _Script(_status(429, **{"Retry-After": "3600"})), []
    with pytest.raises(ProviderRateLimitError, match="3600"):
        _run(script, sleeps)
    assert sleeps == []
    assert len(script.calls) == 1


def test_a_rate_limit_that_never_clears_is_reported_with_advice() -> None:
    script, sleeps = _Script(*[_status(429)] * 4), []
    with pytest.raises(ProviderRateLimitError, match=r"(?i)rate limit.*wait"):
        _run(script, sleeps)
    assert sleeps == [1.0, 2.0, 4.0]


@pytest.mark.parametrize("code", [401, 403])
def test_credential_problems_are_not_retried(code: int) -> None:
    script = _Script(_status(code))
    with pytest.raises(ProviderAuthError, match="API key"):
        _run(script, [])
    assert len(script.calls) == 1


def test_an_unknown_symbol_is_not_retried() -> None:
    script = _Script(_status(404))
    with pytest.raises(UnknownSymbolError, match="AAPL"):
        _run(script, [])
    assert len(script.calls) == 1


def test_another_client_error_is_a_provider_error_with_the_status() -> None:
    with pytest.raises(ProviderError, match="400"):
        _run(_Script(_status(400)), [])


def test_the_backoff_is_capped() -> None:
    script, sleeps = _Script(*[_status(500)] * 5), []
    policy = RetryPolicy(max_attempts=5, base_delay_s=10.0, max_delay_s=15.0)
    with pytest.raises(ProviderNetworkError):
        _run(script, sleeps, policy)
    assert sleeps == [10.0, 15.0, 15.0, 15.0]


def test_no_error_message_contains_the_credentials() -> None:
    scripts = [
        _Script(_status(401)),
        _Script(_status(404)),
        _Script(_status(400)),
        _Script(*[_status(500)] * 4),
        _Script(*[_status(429)] * 4),
        _Script(*[OSError(f"connection to {URL} failed")] * 4),
    ]
    for script in scripts:
        with pytest.raises(ProviderError) as excinfo:
            _run(script, [])
        assert SECRET not in str(excinfo.value)


# ------------------------------------------------------------------ the urllib transport


class _Handler(http.server.BaseHTTPRequestHandler):
    seen: ClassVar[list[dict[str, str]]] = []

    def do_GET(self) -> None:
        _Handler.seen.append({"path": self.path, "auth": self.headers.get("Authorization", "")})
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "/target")
            self.end_headers()
            return
        if self.path.startswith("/missing"):
            self.send_response(404)
            self.end_headers()
            return
        body = b'[{"ok": true}]'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def server() -> Iterator[str]:
    _Handler.seen = []
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_the_urllib_transport_sends_headers_and_returns_status_and_body(server: str) -> None:
    response = urllib_transport(timeout=5.0)(f"{server}/prices?x=1", HEADERS)
    assert response.status == 200
    assert response.body == b'[{"ok": true}]'
    assert _Handler.seen == [{"path": "/prices?x=1", "auth": f"Token {SECRET}"}]


def test_the_urllib_transport_returns_an_error_status_instead_of_raising(server: str) -> None:
    response = urllib_transport(timeout=5.0)(f"{server}/missing", {})
    assert response.status == 404


def test_the_urllib_transport_raises_an_oserror_when_nothing_is_listening() -> None:
    with pytest.raises(OSError):  # noqa: PT011
        urllib_transport(timeout=2.0)("http://127.0.0.1:9/", {})


def test_the_urllib_transport_never_follows_a_redirect_so_a_key_cannot_travel(server: str) -> None:
    response = urllib_transport(timeout=5.0)(f"{server}/redirect", HEADERS)
    assert response.status == 302
    assert [seen["path"] for seen in _Handler.seen] == ["/redirect"]


def test_a_redirect_is_reported_as_a_refused_request() -> None:
    script = _Script(_status(302, Location="http://elsewhere.invalid/"))
    with pytest.raises(ProviderError, match="302"):
        _run(script, [])
    assert len(script.calls) == 1


def test_a_half_read_response_is_a_network_error() -> None:
    script = _Script(*[http.client.IncompleteRead(b"x") for _ in range(4)])
    with pytest.raises(ProviderNetworkError):
        _run(script, [])
