import asyncio
import warnings
from collections.abc import AsyncIterable, Mapping, Sequence
from dataclasses import replace
from typing import Any, NoReturn

from aiohttp import (
    BasicAuth,
    ClientHandlerType,
    ClientOSError,
    ClientRequest,
    ClientResponse,
    ClientSession,
    ServerDisconnectedError,
)
from aiohttp.client import DEFAULT_TIMEOUT
from multidict import CIMultiDict
from yarl import URL

from asyncly.client.handlers.base import (
    ResponseHandlersType,
    apply_handler,
)
from asyncly.client.retry import (
    RetryContext,
    RetryEvent,
    RetryObserver,
    RetryPolicy,
    _RetryableResponse,
)
from asyncly.client.timeout import TimeoutType, get_timeout
from asyncly.client.typing import MethodType


def _encode_basic_auth(login: str, password: str, encoding: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return BasicAuth(login, password, encoding).encode()


class BaseHttpClient:
    """Typed base class for building async HTTP API clients.

    Subclass it and add one method per endpoint, delegating to ``_make_req``
    with a mapping of status codes to response handlers. The
    `aiohttp.ClientSession` is injected, so connection pooling and lifecycle
    stay under your control.

    Example:
        ```python
        class CatfactClient(BaseHttpClient):
            FACT_HANDLERS = MappingProxyType({HTTPStatus.OK: parse_model(CatFact)})

            async def fetch_fact(self) -> CatFact:
                return await self._make_req(
                    method=hdrs.METH_GET,
                    url=self._url / "fact",
                    handlers=self.FACT_HANDLERS,
                )
        ```
    """

    __slots__ = ("_url", "_session", "_client_name", "_proxy", "_proxy_auth")

    _url: URL
    _session: ClientSession
    _client_name: str
    _proxy: URL | None
    _proxy_auth: BasicAuth | None

    def __init__(
        self,
        url: URL | str,
        session: ClientSession,
        client_name: str,
        *,
        proxy: URL | str | None = None,
        proxy_auth: BasicAuth | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            url: Base URL the client's endpoints are resolved against.
            session: The `aiohttp.ClientSession` to issue requests with. The
                caller owns its lifecycle.
            client_name: Identifier used in metrics labels and error messages.
            proxy: Default proxy URL for every request. Can be overridden
                per request by passing `proxy=` to `_make_req`.
            proxy_auth: Default `BasicAuth` credentials for the proxy.
        """
        self._url = url if isinstance(url, URL) else URL(url)
        self._session = session
        self._client_name = client_name
        self._proxy = URL(proxy) if isinstance(proxy, str) else proxy
        self._proxy_auth = proxy_auth

    @property
    def url(self) -> URL:
        """The base URL the client was configured with."""
        return self._url

    async def _make_req(
        self,
        method: MethodType,
        url: URL,
        handlers: ResponseHandlersType,
        timeout: TimeoutType = DEFAULT_TIMEOUT,
        *,
        retry: RetryPolicy | None = None,
        retry_observer: RetryObserver | None = None,
        operation: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Issue a request and dispatch the response to a status handler.

        Args:
            method: HTTP method, e.g. `aiohttp.hdrs.METH_GET`.
            url: Fully resolved request URL.
            handlers: Mapping of status code (exact, ``"2xx"`` range, or ``"*"``
                wildcard) to a response handler callable.
            timeout: Per-request timeout; accepts `ClientTimeout`, `timedelta`,
                or a number of seconds.
            retry: Optional retry policy. Without one, a single physical request
                is made exactly as in previous releases.
            retry_observer: Optional synchronous callback for retry decisions.
            operation: Logical operation label used by instrumented clients.
            **kwargs: Extra arguments forwarded to `ClientSession.request`
                (e.g. ``json``, ``params``, ``headers``). Instance-level
                ``proxy`` is injected unless overridden. ``proxy_auth`` is
                normalized into ``proxy_headers`` before the request is made.

        Returns:
            Whatever the matched handler returns.

        Raises:
            UnhandledStatusException: If no handler matches the response status.
        """
        if "proxy" not in kwargs and self._proxy is not None:
            kwargs["proxy"] = self._proxy

        _normalize_auth_kwargs(kwargs, self._proxy_auth, url=url)

        if retry is None:
            return await self._request_once(
                method=method,
                url=url,
                handlers=handlers,
                timeout=timeout,
                operation=operation,
                **kwargs,
            )

        replayable = _is_request_replayable(kwargs)
        for attempt in range(1, retry.max_attempts + 1):
            context = RetryContext(
                method=str(method),
                url=url,
                attempt=attempt,
                max_attempts=retry.max_attempts,
                replayable=replayable,
            )
            try:
                result = await self._request_once(
                    method=method,
                    url=url,
                    handlers=handlers,
                    timeout=timeout,
                    operation=operation,
                    retry=retry,
                    retry_context=context,
                    retry_observer=retry_observer,
                    **kwargs,
                )
            except Exception as exc:  # noqa: BLE001 - policy owns exception filters
                delay = _retry_exception_delay(
                    policy=retry,
                    context=context,
                    observer=retry_observer,
                    caught=exc,
                )
                await asyncio.sleep(delay)
                continue

            if not isinstance(result, _RetryableResponse):
                return result

            delay = retry.get_delay(
                result.context,
                retry_after=result.retry_after,
            )
            _notify_retry_observer(
                retry_observer,
                RetryEvent(
                    kind="scheduled",
                    context=result.context,
                    delay=delay,
                    reason="status",
                ),
            )
            await asyncio.sleep(delay)

        raise RuntimeError("retry loop exited without a result")

    async def _request_once(
        self,
        *,
        method: MethodType,
        url: URL,
        handlers: ResponseHandlersType,
        timeout: TimeoutType,
        operation: str | None = None,
        retry: RetryPolicy | None = None,
        retry_context: RetryContext | None = None,
        retry_observer: RetryObserver | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute and handle one physical HTTP request."""

        if retry is not None:
            user_middlewares = kwargs.get("middlewares") or ()
            kwargs["middlewares"] = (
                _expose_aiohttp_transport_errors,
                *user_middlewares,
            )

        async with self._session.request(
            method=method,
            url=url,
            timeout=get_timeout(timeout),
            **kwargs,
        ) as response:
            if retry is not None and retry_context is not None:
                response_context = replace(
                    retry_context,
                    response_status=response.status,
                )
                if retry._matches_outcome(response_context):
                    suppression = retry._suppression_reason(response_context)
                    if suppression is None:
                        return _RetryableResponse(
                            context=response_context,
                            retry_after=response.headers.get("Retry-After"),
                        )
                    _notify_retry_observer(
                        retry_observer,
                        RetryEvent(
                            kind=(
                                "exhausted"
                                if suppression == "attempts_exhausted"
                                else "suppressed"
                            ),
                            context=response_context,
                            reason=suppression,
                        ),
                    )
            return await apply_handler(
                handlers=handlers,
                response=response,
                client_name=self._client_name,
            )


def _normalize_auth_kwargs(
    kwargs: dict[str, Any], default_proxy_auth: BasicAuth | None, *, url: URL
) -> None:
    auth = kwargs.pop("auth", None)
    if auth is not None:
        if not isinstance(auth, BasicAuth):
            raise TypeError("auth must be an aiohttp.BasicAuth")
        headers = CIMultiDict(kwargs.get("headers") or {})
        if not any(key.lower() == "authorization" for key in headers):
            headers["Authorization"] = _encode_basic_auth(
                auth.login, auth.password, auth.encoding
            )
        kwargs["headers"] = headers

    proxy_auth = kwargs.pop("proxy_auth", default_proxy_auth)
    if proxy_auth is not None and not isinstance(proxy_auth, BasicAuth):
        raise TypeError("proxy_auth must be an aiohttp.BasicAuth")
    request_headers = CIMultiDict(kwargs.get("headers") or {})
    explicit_proxy_authorization = next(
        (
            value
            for key, value in request_headers.items()
            if key.lower() == "proxy-authorization"
        ),
        None,
    )
    if proxy_auth is None and explicit_proxy_authorization is None:
        return
    proxy_headers = CIMultiDict(kwargs.get("proxy_headers") or {})
    if explicit_proxy_authorization is not None:
        proxy_headers["Proxy-Authorization"] = explicit_proxy_authorization
        proxy_headers.popall("Authorization", None)
        kwargs["proxy_headers"] = proxy_headers
        _add_proxy_auth_middleware(kwargs)
        return
    if any(key.lower() == "proxy-authorization" for key in proxy_headers):
        proxy_headers.popall("Authorization", None)
        kwargs["proxy_headers"] = proxy_headers
        _add_proxy_auth_middleware(kwargs)
        return
    assert proxy_auth is not None
    encoded = _encode_basic_auth(
        proxy_auth.login, proxy_auth.password, proxy_auth.encoding
    )
    proxy_headers["Proxy-Authorization"] = encoded
    kwargs["proxy_headers"] = proxy_headers
    _add_proxy_auth_middleware(kwargs)


def _add_proxy_auth_middleware(kwargs: dict[str, Any]) -> None:
    middlewares = kwargs.get("middlewares") or ()
    kwargs["middlewares"] = (_forward_plain_http_proxy_auth, *middlewares)


async def _forward_plain_http_proxy_auth(
    request: ClientRequest, handler: ClientHandlerType
) -> ClientResponse:
    if request.url.scheme == "http" and request.proxy is not None:
        proxy_headers: Mapping[str, str] = request.proxy_headers or {}
        proxy_authorization = proxy_headers.get("Proxy-Authorization")
        if proxy_authorization is not None and not any(
            key.lower() == "proxy-authorization" for key in request.headers
        ):
            request.headers["Proxy-Authorization"] = proxy_authorization
    return await handler(request)


class _ObservableTransportError(Exception):
    def __init__(
        self,
        original: ClientOSError | ServerDisconnectedError,
    ) -> None:
        super().__init__(str(original))
        self.original = original


async def _expose_aiohttp_transport_errors(
    request: ClientRequest,
    handler: ClientHandlerType,
) -> ClientResponse:
    try:
        return await handler(request)
    except (ClientOSError, ServerDisconnectedError) as exc:
        # aiohttp otherwise retries these internally for idempotent methods.
        # Wrapping here makes every socket attempt visible to Asyncly's policy,
        # observer, and instrumentation. The wrapper is unwrapped before it can
        # escape the client.
        raise _ObservableTransportError(exc) from exc


def _notify_retry_observer(
    observer: RetryObserver | None,
    event: RetryEvent,
) -> None:
    if observer is not None:
        observer(event)


def _unwrap_observable_transport_error(caught: BaseException) -> BaseException:
    if isinstance(caught, _ObservableTransportError):
        return caught.original
    return caught


def _retry_exception_delay(
    *,
    policy: RetryPolicy,
    context: RetryContext,
    observer: RetryObserver | None,
    caught: BaseException,
) -> float:
    original = _unwrap_observable_transport_error(caught)
    failed_context = replace(context, exception=original)
    if not policy._matches_outcome(failed_context):
        _raise_original(caught, original)

    suppression = policy._suppression_reason(failed_context)
    if suppression is not None:
        _notify_retry_observer(
            observer,
            RetryEvent(
                kind=(
                    "exhausted" if suppression == "attempts_exhausted" else "suppressed"
                ),
                context=failed_context,
                reason=suppression,
            ),
        )
        _raise_original(caught, original)

    delay = policy.get_delay(failed_context)
    _notify_retry_observer(
        observer,
        RetryEvent(
            kind="scheduled",
            context=failed_context,
            delay=delay,
            reason="exception",
        ),
    )
    return delay


def _raise_original(caught: BaseException, original: BaseException) -> NoReturn:
    if original is caught:
        raise caught.with_traceback(caught.__traceback__)
    raise original.with_traceback(original.__traceback__)


def _is_request_replayable(kwargs: Mapping[str, Any]) -> bool:
    if "data" not in kwargs:
        return True
    return _is_replayable_data(kwargs["data"])


def _is_replayable_data(data: Any) -> bool:
    if data is None or isinstance(
        data,
        str | bytes | bytearray | memoryview | int | float | bool,
    ):
        return True
    if isinstance(data, Mapping):
        return all(_is_replayable_data(value) for value in data.values())
    if isinstance(data, Sequence):
        return all(
            isinstance(item, Sequence)
            and not isinstance(item, str | bytes | bytearray | memoryview)
            and len(item) == 2
            and _is_replayable_data(item[1])
            for item in data
        )
    if isinstance(data, AsyncIterable):
        return False
    return False
