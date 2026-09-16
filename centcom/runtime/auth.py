"""httpx auth and transports for Contro1 runtime connections."""

from __future__ import annotations

import typing

import httpx

from .token_provider import RuntimeTokenProvider


class RuntimeAuth(httpx.Auth):
    """Signs each request with the connection's DPoP key.

    A server nonce challenge is retried once, and a token the server no longer
    accepts is refreshed once. A refusal that carries a remediation is NOT
    retried: a new token cannot fix a suspended connection.
    """

    requires_response_body = False

    def __init__(self, provider: RuntimeTokenProvider, resource: str = "api"):
        self.provider = provider
        self.resource = resource

    def auth_flow(self, request: httpx.Request) -> typing.Generator[httpx.Request, httpx.Response, None]:
        for attempt in range(3):
            headers = self.provider.authorize_headers(request.method, str(request.url), self.resource)
            request.headers["Authorization"] = headers["Authorization"]
            request.headers["DPoP"] = headers["DPoP"]
            response = yield request
            self.provider.observe_nonce(response.headers)
            if response.status_code != 401 or attempt == 2:
                return
            challenge = response.headers.get("www-authenticate", "")
            if "use_dpop_nonce" in challenge:
                continue
            if "invalid_token" in challenge and attempt == 0:
                self.provider.invalidate(self.resource)
                continue
            return


def broker_transport(endpoint: str) -> httpx.BaseTransport:
    """Reach Contro1 through this computer's Contro1 service.

    The service holds the credential, so this process holds none. Unix sockets
    are supported directly; Windows named pipes are not supported by httpx, so
    use the JavaScript SDK, the CLI, or a token there.
    """
    if endpoint.startswith("unix:///"):
        return httpx.HTTPTransport(uds=endpoint[len("unix://"):])
    if endpoint.startswith("npipe:"):
        raise NotImplementedError(
            "Windows named pipes are not supported by httpx. Use `contro1` (the CLI) "
            "or the JavaScript SDK on Windows, or run this process on Linux or macOS."
        )
    raise ValueError("endpoint must be unix:///<path> (or npipe:// on a platform that supports it)")
