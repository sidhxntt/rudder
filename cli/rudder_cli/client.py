"""The SDK client, plus the one place HTTP failures become readable messages.

Everything the CLI does goes through :class:`Api`. It holds the generated
``AuthenticatedClient`` and turns three kinds of failure into a single
``CliError`` carrying one line of prose:

* transport failure — control plane down, DNS, timeout
* a ``{code, message, details}`` error envelope from the API
* an unexpected status with a body that is not an envelope

No traceback ever reaches the user; ``main.py`` prints ``CliError.message`` and
exits non-zero.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from rudder_sdk import AuthenticatedClient, Client
from rudder_sdk.types import Response

# 204 is here because DELETE endpoints return it with an empty body.
_SUCCESS = frozenset({200, 201, 202, 204})


class CliError(Exception):
    """Anything the user should see as one line on stderr."""

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def _envelope(content: bytes) -> tuple[str | None, str | None]:
    """Pull ``code`` and ``message`` out of an error body, if it is one."""
    if not content:
        return None, None
    try:
        body = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, None
    if not isinstance(body, dict):
        return None, None
    code = body.get("code")
    message = body.get("message")
    return (
        code if isinstance(code, str) else None,
        message if isinstance(message, str) else None,
    )


@dataclass(slots=True)
class Api:
    """A configured client. Construct with :func:`connect`."""

    client: AuthenticatedClient | Client
    base_url: str

    def call(self, fn: Callable[..., Response[Any]], *args: Any, **kwargs: Any) -> Any:
        """Invoke a generated ``*_detailed`` operation and return its parsed body.

        Raises ``CliError`` for anything that is not a documented success.
        """
        with self._transport_errors():
            response = fn(*args, client=self.client, **kwargs)
        if response.status_code in _SUCCESS:
            return response.parsed
        raise self._api_error(response.status_code, response.content)

    def request_json(self, method: str, url: str, *, json: dict[str, Any] | None = None) -> Any:
        """Call a newly-added API operation before the generated SDK is refreshed.

        This deliberately reuses the generated SDK's authenticated httpx client;
        it is a small compatibility bridge, not a second transport stack.
        """
        with self._transport_errors():
            response = self.client.get_httpx_client().request(method, url, json=json)
        if response.status_code not in _SUCCESS:
            raise self._api_error(response.status_code, response.content)
        return response.json() if response.content else None

    @contextmanager
    def stream(self, method: str, url: str) -> Iterator[httpx.Response]:
        """Stream a response using the SDK's own authenticated transport.

        The generator has no notion of ``text/event-stream`` and buffers such
        responses whole, so build-log following goes through ``httpx.stream``
        directly. Still the same client, same base URL, same Authorization
        header — not a second HTTP stack.
        """
        http = self.client.get_httpx_client()
        with self._transport_errors():
            with http.stream(method, url, timeout=httpx.Timeout(10.0, read=None)) as response:
                if response.status_code not in _SUCCESS:
                    response.read()
                    raise self._api_error(response.status_code, response.content)
                yield response

    def _api_error(self, status: int, content: bytes) -> CliError:
        code, message = _envelope(content)
        if status == 401:
            return CliError(
                message or "Not authenticated. Run `rudder login`.",
                code=code or "unauthorized",
                status=status,
            )
        if message:
            return CliError(message, code=code, status=status)
        body = content.decode("utf-8", errors="replace").strip()
        return CliError(f"API returned HTTP {status}{': ' + body if body else ''}", status=status)

    @contextmanager
    def _transport_errors(self) -> Iterator[None]:
        try:
            yield
        except httpx.ConnectError as exc:
            raise CliError(
                f"Cannot reach the Rudder control plane at {self.base_url} — is it running?"
            ) from exc
        except httpx.TimeoutException as exc:
            raise CliError(f"Timed out talking to {self.base_url}.") from exc
        except httpx.HTTPError as exc:
            raise CliError(f"HTTP error talking to {self.base_url}: {exc}") from exc

    def close(self) -> None:
        self.client.get_httpx_client().close()


def connect(base_url: str, token: str) -> Api:
    """A client that sends ``Authorization: Bearer <token>`` on every request.

    With no token — before ``rudder login``, and for the login call itself — it
    sends no Authorization header at all rather than an empty one, which httpx
    rejects outright as an illegal header value.
    """
    base_url = base_url.rstrip("/")
    timeout = httpx.Timeout(30.0)
    client: AuthenticatedClient | Client
    if token:
        client = AuthenticatedClient(
            base_url=base_url, token=token, timeout=timeout, raise_on_unexpected_status=False
        )
    else:
        client = Client(base_url=base_url, timeout=timeout, raise_on_unexpected_status=False)
    return Api(client=client, base_url=base_url)
