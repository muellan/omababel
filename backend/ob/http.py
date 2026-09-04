"""The one door every remote source goes through.

:func:`fetch` keeps time-outs, headers, gzip handling and error mapping
consistent.  By default the request is sent by :mod:`ob.impersonate`, which
speaks HTTP the way a browser does -- Chrome's header set in Chrome's
order, a Chrome-shaped TLS handshake, cookies kept between runs and one
request per host at a time -- because the scraped sites answer 403 to
anything that obviously is not a browser.  ``OMABABEL_IMPERSONATE=0`` falls
back to plain urllib, and ``OMABABEL_OFFLINE=1`` turns every network access
into a :class:`FetchError`, which keeps the test suite hermetic.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Dict, Optional, Union

from . import impersonate

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = float(os.environ.get("OMABABEL_TIMEOUT", "12"))


class FetchError(Exception):
    """Network / HTTP failure.  ``status`` is the HTTP code when known."""

    def __init__(self, message: str, status: Optional[int] = None, url: str = ""):
        super().__init__(message)
        self.status = status
        self.url = url


class Response:
    def __init__(self, url: str, status: int, headers: Dict[str, str], body: bytes):
        self.url = url
        self.status = status
        self.headers = headers
        self.body = body

    @property
    def text(self) -> str:
        charset = "utf-8"
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            charset = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)


def _decompress(body: bytes, encoding: str) -> bytes:
    enc = (encoding or "").lower()
    if enc == "gzip" or enc == "x-gzip":
        return gzip.GzipFile(fileobj=io.BytesIO(body)).read()
    if enc == "deflate":
        try:
            return zlib.decompress(body)
        except zlib.error:
            return zlib.decompress(body, -zlib.MAX_WBITS)
    return body


def fetch(
    url: str,
    *,
    data: Union[bytes, str, dict, None] = None,
    headers: Optional[Dict[str, str]] = None,
    method: Optional[str] = None,
    timeout: Optional[float] = None,
    json_body: Optional[object] = None,
    accept_language: str = "en,de;q=0.8",
) -> Response:
    if os.environ.get("OMABABEL_OFFLINE"):
        raise FetchError("offline mode (OMABABEL_OFFLINE is set)", url=url)

    hdrs = {
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": accept_language,
        "Accept-Encoding": "gzip, deflate",
    }
    if headers:
        hdrs.update(headers)

    payload: Optional[bytes] = None
    if json_body is not None:
        payload = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    elif isinstance(data, dict):
        payload = urllib.parse.urlencode(data).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif isinstance(data, str):
        payload = data.encode("utf-8")
    elif isinstance(data, bytes):
        payload = data

    if impersonate.enabled():
        return _fetch_as_browser(url, payload, headers or {}, method,
                                 timeout or DEFAULT_TIMEOUT, accept_language)

    req = urllib.request.Request(url, data=payload, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout or DEFAULT_TIMEOUT) as resp:
            raw = resp.read()
            rh = {k.lower(): v for k, v in resp.headers.items()}
            body = _decompress(raw, rh.get("content-encoding", ""))
            return Response(resp.geturl(), resp.status, rh, body)
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
            rh = {k.lower(): v for k, v in e.headers.items()}
            body = _decompress(raw, rh.get("content-encoding", ""))
        except Exception:  # pragma: no cover - defensive
            body, rh = b"", {}
        err = FetchError(f"HTTP {e.code} for {url}", status=e.code, url=url)
        err.body = body  # type: ignore[attr-defined]
        err.headers = rh  # type: ignore[attr-defined]
        raise err
    except urllib.error.URLError as e:
        raise FetchError(f"{e.reason} ({url})", url=url)
    except socket.timeout:
        raise FetchError(f"timeout ({url})", url=url)
    except (ConnectionError, OSError) as e:
        raise FetchError(f"{e} ({url})", url=url)


def _fetch_as_browser(url: str, payload: Optional[bytes], headers: Dict[str, str],
                      method: Optional[str], timeout: float, accept_language: str) -> Response:
    """Send through ob.impersonate, escalating to a real Chrome handshake
    (curl-impersonate) for a host that refuses us anyway."""
    host = urllib.parse.urlsplit(url).hostname or ""
    attempts = ["python"]
    if impersonate.state().refusals(host) and impersonate.impersonate_binary():
        attempts.insert(0, "binary")
    elif impersonate.impersonate_binary():
        attempts.append("binary")
    last: Optional[impersonate.ImpersonateError] = None
    for how in attempts:
        try:
            if how == "binary":
                reply = impersonate.fetch_with_binary(url, headers=headers, data=payload,
                                                      method=method, timeout=timeout)
            else:
                reply = impersonate.fetch(url, data=payload, headers=headers, method=method,
                                          timeout=timeout, accept_language=accept_language)
            return Response(reply.url, reply.status,
                            {k.lower(): v for k, v in reply.headers}, reply.body)
        except impersonate.ImpersonateError as e:
            last = e
            # Only a refusal is worth a second identity; a 404 stays a 404.
            if e.status not in (403, 429, 503, None):
                break
    err = FetchError(str(last), status=getattr(last, "status", None), url=url)
    err.body = getattr(last, "body", b"")            # type: ignore[attr-defined]
    err.headers = {k.lower(): v for k, v in getattr(last, "headers", [])}   # type: ignore[attr-defined]
    raise err


def quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def fill_template(template: str, **values: str) -> str:
    """Replace ``{word}``/``{from}``/``{to}`` placeholders, URL-encoded."""
    out = template
    for key, val in values.items():
        out = out.replace("{" + key + "}", quote(val))
    return out
