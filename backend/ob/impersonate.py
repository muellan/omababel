"""Talk to web sources the way a browser does.

Scraping sources (LEO, Duden, Merriam-Webster, Thesaurus.com …) start
answering ``403`` after a handful of requests: what gives a plain script
away is not one thing but a stack of them – the TLS handshake, the set and
the order of the request headers, the absence of cookies, and a request
rate no human produces.  This module is the plugin's own answer to that,
with no third-party module to install: it speaks HTTP itself
(:mod:`http.client`, so the header order is exactly ours), hands OpenSSL a
Chrome-shaped handshake, keeps cookies between runs, and paces requests per
host with a backoff that survives the process.

What it does, in the order it matters:

* **Credentials.**  A request that authenticates us goes over https or not
  at all, and neither an API key nor a cookie ever survives a redirect to
  another origin.
* **Cookies.**  A session cookie is what separates a returning browser from
  a fresh script.  They are kept in the cache directory and replayed.
* **Header set and order.**  Chrome's exact list, in Chrome's order,
  including the client hints and ``Sec-Fetch-*`` – a server matching on
  header order sees a browser.
* **Rate.**  A minimum gap per host plus jitter, and after a 403/429 a
  backoff (honouring ``Retry-After``) that is written to disk, so the next
  process does not walk straight back into the block.
* **TLS.**  Chrome's cipher list and curve preference, TLS 1.2+, no
  compression.  This shapes the handshake as far as OpenSSL lets a Python
  program shape it.  ALPN offers ``http/1.1`` only: a browser also offers
  ``h2``, but a server that then selects it would drop us, since the
  standard library speaks HTTP/1.1.
* **A real Chrome handshake, when available.**  A byte-exact TLS
  fingerprint needs a patched TLS stack; if the box has one --
  ``curl-impersonate`` (``curl_chrome*``) or ``curl`` built against it --
  it is used for hosts that keep answering 403.  Nothing is required for
  the plugin to work.

Set ``OMABABEL_IMPERSONATE=0`` to fall back to plain urllib.
"""

from __future__ import annotations

import gzip
import http.client
import io
import json
import os
import random
import shutil
import socket
import ssl
import subprocess
import time
import urllib.parse
import zlib
from typing import Dict, List, Optional, Tuple

from .paths import cache_dir

# --------------------------------------------------------------- profiles

# Chrome's TLS 1.2 cipher list, in Chrome's order.  The TLS 1.3 suites are
# not part of this string (OpenSSL keeps them in a separate list and orders
# them the way Chrome does anyway).
CHROME_CIPHERS = ":".join([
    "ECDHE-ECDSA-AES128-GCM-SHA256",
    "ECDHE-RSA-AES128-GCM-SHA256",
    "ECDHE-ECDSA-AES256-GCM-SHA384",
    "ECDHE-RSA-AES256-GCM-SHA384",
    "ECDHE-ECDSA-CHACHA20-POLY1305",
    "ECDHE-RSA-CHACHA20-POLY1305",
    "ECDHE-RSA-AES128-SHA",
    "ECDHE-RSA-AES256-SHA",
    "AES128-GCM-SHA256",
    "AES256-GCM-SHA384",
    "AES128-SHA",
    "AES256-SHA",
])
FIREFOX_CIPHERS = ":".join([
    "ECDHE-ECDSA-AES128-GCM-SHA256",
    "ECDHE-RSA-AES128-GCM-SHA256",
    "ECDHE-ECDSA-CHACHA20-POLY1305",
    "ECDHE-RSA-CHACHA20-POLY1305",
    "ECDHE-ECDSA-AES256-GCM-SHA384",
    "ECDHE-RSA-AES256-GCM-SHA384",
    "ECDHE-ECDSA-AES256-SHA",
    "ECDHE-ECDSA-AES128-SHA",
    "ECDHE-RSA-AES128-SHA",
    "ECDHE-RSA-AES256-SHA",
    "AES128-GCM-SHA256",
    "AES256-GCM-SHA384",
])


class Profile:
    """One browser identity: what it sends and how it shakes hands."""

    def __init__(self, name: str, ua: str, ciphers: str, curve: str,
                 headers: List[Tuple[str, str]], impersonate: str = ""):
        self.name = name
        self.ua = ua
        self.ciphers = ciphers
        self.curve = curve
        self.headers = headers            # ordered, {ua} substituted
        self.impersonate = impersonate    # curl-impersonate target name

    def header_list(self) -> List[Tuple[str, str]]:
        return [(k, v.replace("{ua}", self.ua)) for k, v in self.headers]


_CHROME_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")
_FIREFOX_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0"

# Chrome's request header order for a top level navigation.  `Accept-Encoding`
# deliberately omits br/zstd: the standard library cannot decode either, and a
# body we cannot read is worse than a slightly narrower encoding list.
CHROME_HEADERS = [
    ("sec-ch-ua", '"Chromium";v="131", "Not_A Brand";v="24", "Google Chrome";v="131"'),
    ("sec-ch-ua-mobile", "?0"),
    ("sec-ch-ua-platform", '"Linux"'),
    ("Upgrade-Insecure-Requests", "1"),
    ("User-Agent", "{ua}"),
    ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
               "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"),
    ("Sec-Fetch-Site", "none"),
    ("Sec-Fetch-Mode", "navigate"),
    ("Sec-Fetch-User", "?1"),
    ("Sec-Fetch-Dest", "document"),
    ("Accept-Encoding", "gzip, deflate"),
    ("Accept-Language", "en-US,en;q=0.9"),
    ("Priority", "u=0, i"),
]
FIREFOX_HEADERS = [
    ("User-Agent", "{ua}"),
    ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    ("Accept-Language", "en-US,en;q=0.5"),
    ("Accept-Encoding", "gzip, deflate"),
    ("Upgrade-Insecure-Requests", "1"),
    ("Sec-Fetch-Dest", "document"),
    ("Sec-Fetch-Mode", "navigate"),
    ("Sec-Fetch-Site", "none"),
    ("Sec-Fetch-User", "?1"),
]

PROFILES = {
    "chrome": Profile("chrome", _CHROME_UA, CHROME_CIPHERS, "X25519", CHROME_HEADERS, "chrome131"),
    "firefox": Profile("firefox", _FIREFOX_UA, FIREFOX_CIPHERS, "X25519", FIREFOX_HEADERS, "ff117"),
}
DEFAULT_PROFILE = "chrome"

# Pacing.  A browser does not fetch the same host twice in the same
# millisecond, and a source that just refused us deserves a rest.
MIN_INTERVAL = float(os.environ.get("OMABABEL_HOST_INTERVAL", "0.8"))
MAX_RETRIES = int(os.environ.get("OMABABEL_HTTP_RETRIES", "2"))
BLOCK_BACKOFF = (20.0, 60.0, 300.0)      # after 1, 2, 3+ refusals in a row
MAX_REDIRECTS = 5

# ----------------------------------------------------------- credentials
#
# Headers that authenticate us.  They are never sent over plaintext http and
# never survive a redirect to another origin: where the next request goes is
# the remote party's suggestion, and it must not be able to name itself as
# the recipient of our API key.
SENSITIVE_HEADERS = frozenset({
    "authorization", "proxy-authorization", "cookie", "x-api-key", "api-key",
    "x-goog-api-key", "x-goog-iam-authorization-token", "x-auth-token",
    "x-access-token", "x-session-token", "x-amz-security-token",
    "openai-organization", "anthropic-version",
})


def is_sensitive(name: str) -> bool:
    return str(name).lower() in SENSITIVE_HEADERS


def has_credentials(headers) -> bool:
    if not headers:
        return False
    names = headers.keys() if hasattr(headers, "keys") else [k for k, _ in headers]
    return any(is_sensitive(k) for k in names)


def origin_of(url: str):
    parts = urllib.parse.urlsplit(url)
    scheme = (parts.scheme or "").lower()
    port = parts.port or (443 if scheme == "https" else (80 if scheme == "http" else 0))
    return (scheme, (parts.hostname or "").lower(), port)


def same_origin(a: str, b: str) -> bool:
    return origin_of(a) == origin_of(b)


def require_secure(url: str, headers=None) -> None:
    """Refuse to put a credential on the wire in the clear."""
    if not has_credentials(headers):
        return
    if origin_of(url)[0] != "https":
        raise ImpersonateError(
            "refusing to send credentials over plain http; use an https endpoint", url=url)


def strip_credentials(headers):
    """The caller's headers without anything that authenticates us."""
    if not headers:
        return headers
    if hasattr(headers, "items"):
        return {k: v for k, v in headers.items() if not is_sensitive(k)}
    return [(k, v) for k, v in headers if not is_sensitive(k)]


def check_redirect(url: str, location: str, headers=None) -> str:
    """The absolute target of a redirect, or an error when it must not be
    followed: only http(s), never a downgrade from https, and never a
    credentialed request to another origin."""
    target = urllib.parse.urljoin(url, str(location or ""))
    scheme, host, _ = origin_of(target)
    if scheme not in ("http", "https") or not host:
        raise ImpersonateError(f"refusing to follow a redirect to {target!r}", url=url)
    if origin_of(url)[0] == "https" and scheme != "https":
        raise ImpersonateError("refusing to follow a redirect from https to plain http", url=url)
    if has_credentials(headers) and not same_origin(url, target):
        raise ImpersonateError(
            "refusing to follow a cross-origin redirect on a request that carries credentials",
            url=url)
    return target


def enabled() -> bool:
    return os.environ.get("OMABABEL_IMPERSONATE", "1") not in ("0", "false", "no")


def profile_for(name: str = "") -> Profile:
    return PROFILES.get((name or os.environ.get("OMABABEL_PROFILE") or DEFAULT_PROFILE).lower(),
                        PROFILES[DEFAULT_PROFILE])


# ------------------------------------------------------------------ state
#
# Cookies and per-host pacing outlive the process: the backend runs as one
# process per request, so keeping either only in memory would throw away
# exactly the state that makes a client look like a returning browser.

class _State:
    """cookies + host pacing, in one small JSON file."""

    FILE = "browser-state.json"

    def __init__(self, path=None):
        self.path = path or (cache_dir() / self.FILE)
        self.data = {"cookies": {}, "hosts": {}}
        try:
            with open(self.path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                self.data.update({k: v for k, v in loaded.items() if isinstance(v, dict)})
        except (OSError, ValueError):
            pass
        self.dirty = False

    # -- cookies ------------------------------------------------------
    def cookies_for(self, host: str, path: str, secure: bool) -> str:
        now = time.time()
        out = []
        for domain, jar in self.data.get("cookies", {}).items():
            if not _domain_match(host, domain):
                continue
            for name, c in list(jar.items()):
                if c.get("expires") and c["expires"] < now:
                    del jar[name]
                    self.dirty = True
                    continue
                if not path.startswith(c.get("path", "/")):
                    continue
                if c.get("secure") and not secure:
                    continue
                out.append(f"{name}={c['value']}")
        return "; ".join(out)

    def store_cookies(self, host: str, headers: List[Tuple[str, str]]) -> None:
        for key, value in headers:
            if key.lower() != "set-cookie":
                continue
            parsed = _parse_set_cookie(value, host)
            if not parsed:
                continue
            domain, name, cookie = parsed
            jar = self.data.setdefault("cookies", {}).setdefault(domain, {})
            jar[name] = cookie
            self.dirty = True

    # -- pacing -------------------------------------------------------
    def host(self, host: str) -> dict:
        return self.data.setdefault("hosts", {}).setdefault(host, {})

    def wait_for(self, host: str) -> float:
        """Seconds to wait before the next request to this host."""
        info = self.host(host)
        now = time.time()
        blocked = float(info.get("blocked_until", 0))
        gap = MIN_INTERVAL + random.uniform(0, MIN_INTERVAL / 2)
        earliest = max(blocked, float(info.get("last", 0)) + gap)
        return max(0.0, earliest - now)

    def mark_request(self, host: str) -> None:
        self.host(host)["last"] = time.time()
        self.dirty = True

    def mark_ok(self, host: str) -> None:
        info = self.host(host)
        info.pop("refusals", None)
        info.pop("blocked_until", None)
        info["last"] = time.time()
        self.dirty = True

    def mark_refused(self, host: str, retry_after: float = 0.0) -> float:
        info = self.host(host)
        n = int(info.get("refusals", 0)) + 1
        info["refusals"] = n
        pause = retry_after or BLOCK_BACKOFF[min(n, len(BLOCK_BACKOFF)) - 1]
        info["blocked_until"] = time.time() + pause
        self.dirty = True
        return pause

    def refusals(self, host: str) -> int:
        return int(self.host(host).get("refusals", 0))

    def save(self) -> None:
        if not self.dirty:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
            self.dirty = False
        except OSError:
            pass


_state: Optional[_State] = None


def state() -> _State:
    global _state
    if _state is None:
        _state = _State()
    return _state


def reset_state() -> None:
    """Drop the in-process handle (tests, and after the cache is cleared)."""
    global _state
    _state = None


def _domain_match(host: str, domain: str) -> bool:
    host = host.lower()
    domain = domain.lower().lstrip(".")
    return host == domain or host.endswith("." + domain)


def _parse_set_cookie(value: str, host: str):
    parts = [p.strip() for p in value.split(";") if p.strip()]
    if not parts or "=" not in parts[0]:
        return None
    name, _, val = parts[0].partition("=")
    cookie = {"value": val, "path": "/", "secure": False, "expires": 0}
    domain = host
    for attr in parts[1:]:
        key, _, av = attr.partition("=")
        key = key.strip().lower()
        av = av.strip()
        if key == "domain" and av:
            domain = av.lstrip(".")
        elif key == "path" and av.startswith("/"):
            cookie["path"] = av
        elif key == "secure":
            cookie["secure"] = True
        elif key == "max-age":
            try:
                cookie["expires"] = time.time() + int(av)
            except ValueError:
                pass
        elif key == "expires" and not cookie["expires"]:
            cookie["expires"] = _http_date(av)
    if not _domain_match(host, domain):
        domain = host
    return domain, name.strip(), cookie


def _http_date(value: str) -> float:
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError, IndexError):
        return 0.0


# -------------------------------------------------------------------- TLS

def build_context(profile: Profile) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    try:
        ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
    except (OSError, ssl.SSLError):
        pass
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        ctx.set_ciphers(profile.ciphers)
    except ssl.SSLError:
        pass
    try:
        ctx.set_ecdh_curve(profile.curve)
    except (ValueError, ssl.SSLError):
        pass
    # Only http/1.1: a browser also offers h2, but a server that then selects
    # it drops a client that goes on to speak HTTP/1.1 -- which is what the
    # standard library speaks.  Offering what we can actually do is the one
    # place where honesty beats a closer fingerprint.
    try:
        ctx.set_alpn_protocols(["http/1.1"])
    except NotImplementedError:
        pass
    ctx.options |= ssl.OP_NO_COMPRESSION
    if hasattr(ssl, "OP_ENABLE_MIDDLEBOX_COMPAT"):
        ctx.options |= ssl.OP_ENABLE_MIDDLEBOX_COMPAT
    ctx.post_handshake_auth = False
    return ctx


# ---------------------------------------------------------------- request

class Reply:
    """Raw reply: the caller (ob.http) wraps it in its own Response."""

    def __init__(self, url: str, status: int, headers: List[Tuple[str, str]], body: bytes):
        self.url = url
        self.status = status
        self.headers = headers
        self.body = body

    def header(self, name: str, default: str = "") -> str:
        for k, v in self.headers:
            if k.lower() == name.lower():
                return v
        return default


class ImpersonateError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, url: str = "",
                 body: bytes = b"", headers: Optional[List[Tuple[str, str]]] = None):
        super().__init__(message)
        self.status = status
        self.url = url
        self.body = body
        self.headers = headers or []


def proxy_for(host: str, secure: bool) -> str:
    """The proxy this host should go through, honouring NO_PROXY."""
    no_proxy = os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or ""
    for entry in no_proxy.split(","):
        entry = entry.strip().lstrip(".").lower()
        if entry and (host.lower() == entry or host.lower().endswith("." + entry) or entry == "*"):
            return ""
    for name in (("https_proxy", "HTTPS_PROXY") if secure else ("http_proxy", "HTTP_PROXY")) + \
                ("all_proxy", "ALL_PROXY"):
        value = os.environ.get(name)
        if value:
            return value
    return ""


def _connection(host: str, port: int, secure: bool, timeout: float, profile: Profile):
    """A connection to `host`, through the environment's proxy if there is one.

    For an https target the proxy is tunnelled: HTTPSConnection sends the
    CONNECT over the raw socket first and only then wraps *the tunnel* in
    TLS, so the handshake -- and therefore the fingerprint -- is with the
    target, not with the proxy.
    """
    proxy = proxy_for(host, secure)
    if proxy:
        parts = urllib.parse.urlsplit(proxy if "//" in proxy else "//" + proxy)
        proxy_host = parts.hostname or "127.0.0.1"
        proxy_port = parts.port or (443 if parts.scheme == "https" else 80)
        headers = {}
        if parts.username:
            import base64
            token = base64.b64encode(f"{parts.username}:{parts.password or ''}".encode()).decode()
            headers["Proxy-Authorization"] = "Basic " + token
        if secure:
            conn = http.client.HTTPSConnection(proxy_host, proxy_port, timeout=timeout,
                                               context=build_context(profile))
            conn.set_tunnel(host, port, headers=headers)
            return conn
        # A plain http target is proxied by asking for the absolute URL; see
        # `fetch`, which builds the request line accordingly.
        conn = http.client.HTTPConnection(proxy_host, proxy_port, timeout=timeout)
        conn.omababel_proxy_headers = headers      # merged in by `fetch`
        return conn
    if secure:
        return http.client.HTTPSConnection(host, port, timeout=timeout,
                                           context=build_context(profile))
    return http.client.HTTPConnection(host, port, timeout=timeout)


# Swapped out in tests.
connection_factory = _connection


def _decompress(body: bytes, encoding: str) -> bytes:
    enc = (encoding or "").lower()
    try:
        if enc in ("gzip", "x-gzip"):
            return gzip.GzipFile(fileobj=io.BytesIO(body)).read()
        if enc == "deflate":
            try:
                return zlib.decompress(body)
            except zlib.error:
                return zlib.decompress(body, -zlib.MAX_WBITS)
    except (OSError, zlib.error):
        return body
    return body


def _merge_headers(profile: Profile, url: str, extra: Optional[Dict[str, str]],
                   accept_language: str, body: Optional[bytes], cookie: str) -> List[Tuple[str, str]]:
    """Chrome's headers, in Chrome's order, with the caller's on top."""
    parts = urllib.parse.urlsplit(url)
    extra = {k: v for k, v in (extra or {}).items()}
    out: List[Tuple[str, str]] = [("Host", parts.netloc), ("Connection", "keep-alive")]
    for key, value in profile.header_list():
        if key.lower() == "accept-language" and accept_language:
            value = accept_language
        lowered = {k.lower(): k for k in extra}
        if key.lower() in lowered:
            value = extra.pop(lowered[key.lower()])
        out.append((key, value))
    # A browser arrives from somewhere: a same-site referer is both realistic
    # and what several of the scraped sites check.
    if not any(k.lower() == "referer" for k, _ in out) and "referer" not in {k.lower() for k in extra}:
        out.insert(len(out) - 2, ("Referer", f"{parts.scheme}://{parts.netloc}/"))
    if body is not None:
        out.append(("Content-Length", str(len(body))))
    for key, value in extra.items():           # whatever the caller added
        out.append((key, value))
    if cookie:
        out.append(("Cookie", cookie))
    return out


def fetch(url: str, *, data: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None,
          method: Optional[str] = None, timeout: float = 15.0,
          accept_language: str = "en-US,en;q=0.9", profile: Optional[Profile] = None,
          _redirects: int = 0) -> Reply:
    """One request, as a browser would send it."""
    prof = profile or profile_for()
    require_secure(url, headers)          # no credentials over plain http
    st = state()
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    secure = parts.scheme != "http"
    port = parts.port or (443 if secure else 80)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query

    wait = st.wait_for(host)
    if wait > 0:
        if wait > timeout:
            raise ImpersonateError(
                f"{host} refused the last request; waiting {int(wait)}s before trying again",
                status=429, url=url)
        time.sleep(wait)

    # A plain http request through a proxy carries the absolute URL.
    if not secure and proxy_for(host, secure):
        path = f"http://{host}:{port}{path}" if port != 80 else f"http://{host}{path}"

    verb = method or ("POST" if data is not None else "GET")
    request_headers = _merge_headers(prof, url, headers, accept_language, data,
                                     st.cookies_for(host, path.split("?")[0], secure))
    conn = connection_factory(host, port, secure, timeout, prof)
    request_headers += list(getattr(conn, "omababel_proxy_headers", {}).items())
    try:
        conn.putrequest(verb, path, skip_host=True, skip_accept_encoding=True)
        for key, value in request_headers:
            conn.putheader(key, value)
        conn.endheaders(data if data else None)
        st.mark_request(host)
        resp = conn.getresponse()
        raw = resp.read()
        reply_headers = list(resp.getheaders())
        status = resp.status
    except (OSError, http.client.HTTPException) as e:
        raise ImpersonateError(f"{e} ({url})", url=url)
    finally:
        try:
            conn.close()
        except Exception:      # noqa: BLE001 - closing must never mask the error
            pass

    st.store_cookies(host, reply_headers)
    body = _decompress(raw, dict((k.lower(), v) for k, v in reply_headers).get("content-encoding", ""))
    reply = Reply(url, status, reply_headers, body)

    if status in (301, 302, 303, 307, 308) and _redirects < MAX_REDIRECTS:
        location = reply.header("location")
        if location:
            # Where the next request goes is the remote party's suggestion, so
            # it is checked before it is taken, and nothing that authenticates
            # us travels to another origin.
            target = check_redirect(url, location, headers)
            st.mark_ok(host)
            st.save()
            follow_headers = headers if same_origin(url, target) else strip_credentials(headers)
            follow_data = None if status in (301, 302, 303) else data
            follow_method = "GET" if status in (301, 302, 303) else verb
            return fetch(target, data=follow_data, headers=follow_headers, method=follow_method,
                         timeout=timeout, accept_language=accept_language, profile=prof,
                         _redirects=_redirects + 1)

    if status in (403, 429, 503):
        retry_after = 0.0
        try:
            retry_after = float(reply.header("retry-after") or 0)
        except ValueError:
            retry_after = 0.0
        pause = st.mark_refused(host, retry_after)
        st.save()
        raise ImpersonateError(f"HTTP {status} for {url} (rate limited; pausing {int(pause)}s)",
                               status=status, url=url, body=body, headers=reply_headers)
    if status >= 400:
        st.mark_ok(host)
        st.save()
        raise ImpersonateError(f"HTTP {status} for {url}", status=status, url=url,
                               body=body, headers=reply_headers)
    st.mark_ok(host)
    st.save()
    return reply


# ------------------------------------------------- real Chrome handshake
#
# Everything above shapes the handshake as far as OpenSSL allows.  A
# byte-exact Chrome fingerprint needs a TLS stack built for it; if the box
# has one, use it for the hosts that keep refusing.

IMPERSONATE_BINARIES = ("curl_chrome131", "curl_chrome124", "curl_chrome116",
                        "curl-impersonate-chrome", "curl-impersonate")


def impersonate_binary() -> str:
    override = os.environ.get("OMABABEL_CURL_IMPERSONATE")
    if override:
        return override if os.access(override, os.X_OK) else (shutil.which(override) or "")
    for name in IMPERSONATE_BINARIES:
        found = shutil.which(name)
        if found:
            return found
    return ""


def fetch_with_binary(url: str, *, headers: Optional[Dict[str, str]] = None,
                      data: Optional[bytes] = None, method: Optional[str] = None,
                      timeout: float = 20.0, profile: Optional[Profile] = None) -> Reply:
    """Same request through curl-impersonate (a real Chrome fingerprint)."""
    binary = impersonate_binary()
    if not binary:
        raise ImpersonateError("no curl-impersonate on this system", url=url)
    require_secure(url, headers)
    prof = profile or profile_for()
    argv = [binary, "-sS", "-i", "--compressed", "--max-time", str(int(timeout))]
    if os.path.basename(binary).startswith("curl-impersonate"):
        argv += ["--impersonate", prof.impersonate]
    for key, value in _merge_headers(prof, url, headers, "", data,
                                     state().cookies_for(urllib.parse.urlsplit(url).hostname or "",
                                                         "/", True)):
        if key.lower() in ("host", "content-length", "connection"):
            continue
        argv += ["-H", f"{key}: {value}"]
    if data is not None:
        argv += ["--data-binary", "@-"]
    if method:
        argv += ["-X", method]
    argv.append(url)
    try:
        proc = subprocess.run(argv, input=data or b"", capture_output=True, timeout=timeout + 5)
    except (OSError, subprocess.SubprocessError) as e:
        raise ImpersonateError(str(e), url=url)
    if proc.returncode != 0:
        raise ImpersonateError((proc.stderr.decode("utf-8", "replace").strip()
                                or f"curl exited {proc.returncode}"), url=url)
    head, _, body = proc.stdout.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1").split("\r\n")
    status = 0
    out_headers: List[Tuple[str, str]] = []
    for line in lines:
        if line.startswith("HTTP/"):
            bits = line.split(" ", 2)
            status = int(bits[1]) if len(bits) > 1 and bits[1].isdigit() else 0
            out_headers = []
        elif ":" in line:
            key, _, value = line.partition(":")
            out_headers.append((key.strip(), value.strip()))
    if status >= 400:
        raise ImpersonateError(f"HTTP {status} for {url}", status=status, url=url,
                               body=body, headers=out_headers)
    return Reply(url, status or 200, out_headers, body)


def sleep_jitter(seconds: float) -> None:      # pragma: no cover - timing helper
    time.sleep(seconds + random.uniform(0, seconds / 3))
