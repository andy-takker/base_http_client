# aiohttp Authentication Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve Asyncly client and proxy authentication on aiohttp 3.13.3 and 3.14 without forwarding deprecated aiohttp auth parameters.

**Architecture:** Normalize `auth` and `proxy_auth` at `BaseHttpClient._make_req`'s request boundary. Convert `BasicAuth` values to public aiohttp-encoded headers, merge them without overriding explicit caller headers, and pass only header-based auth to `ClientSession.request`.

**Tech Stack:** Python 3.10+, aiohttp 3.13.3–3.14, pytest, pytest-asyncio, multidict.

## Global Constraints

- Keep the existing public `proxy_auth: BasicAuth | None` constructor API.
- Support the declared aiohttp floor `>=3.13.3,<4`.
- Use public aiohttp `encode_basic_auth` and `proxy_headers`; do not add version branching or transport internals.
- Explicit caller headers remain authoritative over generated auth headers.

---

### Task 1: Normalize client and proxy authentication at the request boundary

**Files:**
- Modify: `asyncly/client/base.py:7-220` (imports and `_make_req` request kwargs normalization)
- Test: `tests/srvmocker/test_proxy.py` (client auth and proxy-auth regression coverage)

**Interfaces:**
- Consumes: existing `BaseHttpClient._make_req(..., **kwargs)` and constructor `proxy_auth` injection.
- Produces: requests that carry `Authorization` and `Proxy-Authorization` through headers while omitting deprecated `auth` and `proxy_auth` kwargs.

- [ ] **Step 1: Write failing tests for ordinary client auth and warning-free proxy auth**

Add tests that:

```python
async def test_client_auth_uses_authorization_header() -> None:
    # Start a target route, call `_make_req(..., auth=BasicAuth(...))`, and
    # assert the recorded request has the encoded Authorization header.

async def test_client_proxy_auth_constructor_is_warning_free() -> None:
    # Use `warnings.catch_warnings(record=True)` with `simplefilter("always")`,
    # make a request through an authenticated proxy using constructor
    # `proxy_auth`, then assert no `DeprecationWarning` was emitted.

async def test_client_proxy_auth_per_request_is_forwarded() -> None:
    # Pass `proxy_auth=BasicAuth(...)` directly to `_make_req` and assert the
    # proxy receives the matching Proxy-Authorization header.
```

- [ ] **Step 2: Run the focused tests and verify the expected red failure**

Run:

```bash
rtk uv run pytest tests/srvmocker/test_proxy.py -k "client_auth or proxy_auth" -q
```

Expected: the new tests fail because aiohttp receives deprecated auth kwargs or the normal client auth header is absent.

- [ ] **Step 3: Implement the minimal request-kwargs normalization**

In `asyncly/client/base.py`:

1. Import `encode_basic_auth` from aiohttp.
2. Before the existing default proxy injection, pop `auth` and `proxy_auth` from `kwargs`.
3. If `auth` is present, add `Authorization: encode_basic_auth(auth.login, auth.password, auth.encoding)` only when the caller's `headers` do not already contain `Authorization` (case-insensitive).
4. If `proxy_auth` is present, copy/create `proxy_headers` and add `Proxy-Authorization: encode_basic_auth(...)` only when it is not already present (case-insensitive).
5. Apply the same normalization to constructor-injected `self._proxy_auth`, while preserving an explicit per-request `proxy_auth` override.
6. Leave non-BasicAuth values untouched only if aiohttp's public type accepts them; otherwise raise the same `TypeError` before making a request.

- [ ] **Step 4: Run the focused tests and verify green**

Run:

```bash
rtk uv run pytest tests/srvmocker/test_proxy.py -k "client_auth or proxy_auth" -q
```

Expected: all focused auth tests pass with no deprecation warnings.

- [ ] **Step 5: Run the full validation suite**

Run:

```bash
rtk make test-ci
rtk git diff --check
```

Expected: the complete suite passes and the diff has no whitespace errors.

- [ ] **Step 6: Commit the implementation**

```bash
rtk git add asyncly/client/base.py tests/srvmocker/test_proxy.py
rtk git commit -m "fix: keep aiohttp auth compatible with 3.14"
```
