# aiohttp authentication compatibility

## Goal

Keep Asyncly client and proxy authentication working on aiohttp 3.13.3 and
3.14 while avoiding authentication deprecation warnings ahead of aiohttp 4.0.

## Design

Asyncly keeps its existing public `BasicAuth`-based `proxy_auth` constructor
argument. At the request boundary, authentication arguments are normalized to
headers before calling `ClientSession.request`:

- `auth=BasicAuth(...)` becomes an `Authorization` header.
- `proxy_auth=BasicAuth(...)` becomes a `Proxy-Authorization` entry in
  `proxy_headers`.
- The deprecated aiohttp `auth` and `proxy_auth` keyword arguments are never
  forwarded to aiohttp.
- Explicit per-request headers remain authoritative; generated headers are
  only added when the caller did not provide the corresponding value.

The implementation uses aiohttp's public `encode_basic_auth` helper and
`proxy_headers` request option. No aiohttp version branching or transport
internals are introduced.

## Verification

Regression tests cover constructor-level and per-request proxy credentials,
regular client authentication, header precedence, and a warning-free request
on the installed aiohttp 3.14 release. The existing test suite must remain
green.
